/* ESP32-S3 USB Ethernet uplink -> WPA2 2.4 GHz access point. */
#include <stdatomic.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_defaults.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "lwip/sockets.h"
#include "cJSON.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "tinyusb_net.h"
#include "tinyusb_cdc_acm.h"
#include "tinyusb_console.h"
#include "router_config.h"

/* One NCM configuration: macOS needs no third-party RNDIS driver.
   String IDs match esp_tinyusb's CDC + network string table (MAC = 6). */
static const uint8_t usb_descriptor[] = {
    TUD_CONFIG_DESCRIPTOR(1, 4, 0, TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_CDC_NCM_DESC_LEN, 0, 500),
    TUD_CDC_DESCRIPTOR(0, 4, 0x81, 8, 0x02, 0x82, 64),
    TUD_CDC_NCM_DESCRIPTOR(2, 5, 6, 0x83, 64, 0x04, 0x84, 64, 1514),
};

static const char *TAG = "ap24";
static esp_netif_t *wan, *ap;
static QueueHandle_t tx_queue;
static atomic_bool usb_link, nat_ready, subnet_conflict;
static atomic_uint tx_dropped, rx_dropped;
static atomic_uint dns_queries, dns_failures;
ESP_EVENT_DEFINE_BASE(ROUTER_EVENT);
enum { LINK_UP, LINK_DOWN };
typedef struct { void *data; uint16_t len; } packet_t;

/* lwIP must never wait on the TinyUSB task: the receive path uses lwIP too. */
static esp_err_t usb_transmit(void *handle, void *buffer, size_t len)
{
    if (!atomic_load(&usb_link) || len > 1514) return ESP_FAIL;
    packet_t pkt = { .data = malloc(len), .len = len };
    if (pkt.data) {
        memcpy(pkt.data, buffer, len);
        if (xQueueSend(tx_queue, &pkt, 0) == pdTRUE) return ESP_OK;
        free(pkt.data);
    }
    atomic_fetch_add(&tx_dropped, 1);
    return ESP_ERR_NO_MEM;
}

static void usb_tx_task(void *arg)
{
    packet_t pkt;
    for (;;) {
        if (xQueueReceive(tx_queue, &pkt, portMAX_DELAY) != pdTRUE) continue;
        esp_err_t err = ESP_FAIL;
        /* A busy bulk endpoint is normal; allow a short bounded retry. */
        for (int i = 0; i < 20 && atomic_load(&usb_link); i++) {
            err = tinyusb_net_send_sync(pkt.data, pkt.len, NULL, portMAX_DELAY);
            if (err != ESP_FAIL) break;
            vTaskDelay(1);
        }
        if (err != ESP_OK) atomic_fetch_add(&tx_dropped, 1);
        free(pkt.data);
    }
}

static void usb_free_rx(void *handle, void *buffer) { free(buffer); }

static esp_err_t usb_receive(void *buffer, uint16_t len, void *ctx)
{
    if (!atomic_load(&usb_link) || len > 1514) return ESP_FAIL;
    /* TinyUSB reuses its RX buffer immediately after this callback returns.
       Ethernet esp_netif takes ownership and frees this copy via free_rx. */
    void *copy = malloc(len);
    if (!copy) { atomic_fetch_add(&rx_dropped, 1); return ESP_ERR_NO_MEM; }
    memcpy(copy, buffer, len);
    return esp_netif_receive(wan, copy, len, NULL);
}

static void disable_nat(void)
{
    if (atomic_exchange(&nat_ready, false)) ESP_ERROR_CHECK(esp_netif_napt_disable(ap));
}

static void net_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == ROUTER_EVENT) {
        if (id == LINK_UP && !atomic_exchange(&usb_link, true)) {
            esp_netif_action_start(wan, base, id, NULL);
            esp_netif_action_connected(wan, base, id, NULL);
            ESP_LOGI(TAG, "USB attached; waiting for Mac Internet Sharing DHCP");
        } else if (id == LINK_DOWN && atomic_exchange(&usb_link, false)) {
            disable_nat();
            esp_netif_action_disconnected(wan, base, id, NULL);
            esp_netif_action_stop(wan, base, id, NULL);
            ESP_LOGI(TAG, "USB detached; AP remains available locally");
        }
    } else if (base == IP_EVENT && id == IP_EVENT_ETH_GOT_IP) {
        ip_event_got_ip_t *event = data;
        if (event->esp_netif != wan || !atomic_load(&usb_link)) return;
        disable_nat();
        esp_netif_ip_info_t lan;
        ESP_ERROR_CHECK(esp_netif_get_ip_info(ap, &lan));
        uint32_t mask = event->ip_info.netmask.addr;
        bool overlap = ((lan.ip.addr & mask) == (event->ip_info.ip.addr & mask)) ||
                       ((lan.ip.addr & lan.netmask.addr) == (event->ip_info.ip.addr & lan.netmask.addr));
        atomic_store(&subnet_conflict, overlap);
        if (overlap) {
            ESP_LOGE(TAG, "USB subnet overlaps AP subnet; NAT disabled");
            return;
        }
        ESP_ERROR_CHECK(esp_netif_set_default_netif(wan));
        ESP_ERROR_CHECK(esp_netif_napt_enable(ap));
        atomic_store(&nat_ready, true);
        ESP_LOGI(TAG, "USB IP " IPSTR ", gateway " IPSTR "; NAT enabled",
                 IP2STR(&event->ip_info.ip), IP2STR(&event->ip_info.gw));
    } else if (base == IP_EVENT && id == IP_EVENT_ETH_LOST_IP) {
        disable_nat();
    }
}

static void usb_event(tinyusb_event_t *event, void *arg)
{
    /* Never invoke blocking esp_netif APIs in the USB driver task. */
    if (event->id == TINYUSB_EVENT_ATTACHED || event->id == TINYUSB_EVENT_DETACHED) {
        esp_event_post(ROUTER_EVENT, event->id == TINYUSB_EVENT_ATTACHED ? LINK_UP : LINK_DOWN,
                       NULL, 0, 0);
    }
}

/* A stable AP DNS address lets clients join before Mac sharing is enabled.
   Forward ordinary UDP DNS to the DNS server from the latest USB DHCP lease. */
static void dns_task(void *arg)
{
    int server = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in local = { .sin_family = AF_INET, .sin_port = htons(53) };
    inet_pton(AF_INET, "10.42.32.1", &local.sin_addr);
    if (server < 0 || bind(server, (struct sockaddr *)&local, sizeof(local)) < 0) {
        ESP_LOGE(TAG, "Cannot bind AP DNS server");
        if (server >= 0) close(server);
        vTaskDelete(NULL);
        return;
    }
    uint8_t query[1500], reply[1500];
    for (;;) {
        struct sockaddr_in client;
        socklen_t client_len = sizeof(client);
        int len = recvfrom(server, query, sizeof(query), 0, (struct sockaddr *)&client, &client_len);
        if (len < 12 || (query[2] & 0x80)) continue;
        atomic_fetch_add(&dns_queries, 1);
        int received = -1;
        esp_netif_dns_info_t dns = {0};
        if (atomic_load(&nat_ready) && esp_netif_get_dns_info(wan, ESP_NETIF_DNS_MAIN, &dns) == ESP_OK &&
            dns.ip.type == ESP_IPADDR_TYPE_V4 && dns.ip.u_addr.ip4.addr) {
            int upstream = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
            if (upstream >= 0) {
                struct timeval timeout = { .tv_sec = 2 };
                setsockopt(upstream, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                struct sockaddr_in remote = { .sin_family = AF_INET, .sin_port = htons(53),
                                             .sin_addr.s_addr = dns.ip.u_addr.ip4.addr };
                if (connect(upstream, (struct sockaddr *)&remote, sizeof(remote)) == 0 &&
                    send(upstream, query, len, 0) == len) {
                    received = recv(upstream, reply, sizeof(reply), 0);
                    if (received < 12 || reply[0] != query[0] || reply[1] != query[1] || !(reply[2] & 0x80)) received = -1;
                }
                close(upstream);
            }
        }
        if (received < 0) {
            atomic_fetch_add(&dns_failures, 1);
            memcpy(reply, query, len);
            reply[2] = (query[2] & 0x79) | 0x80;
            reply[3] = 0x82; /* recursion available, SERVFAIL */
            memset(reply + 6, 0, 6);
            received = len;
        }
        sendto(server, reply, received, 0, (struct sockaddr *)&client, client_len);
    }
}

static esp_err_t status_handler(httpd_req_t *req)
{
    esp_netif_ip_info_t ip = {0};
    esp_netif_get_ip_info(wan, &ip);
    wifi_sta_list_t clients = {0};
    esp_wifi_ap_get_sta_list(&clients);
    char addr[16], gw[16];
    snprintf(addr, sizeof(addr), IPSTR, IP2STR(&ip.ip));
    snprintf(gw, sizeof(gw), IPSTR, IP2STR(&ip.gw));
    cJSON *json = cJSON_CreateObject();
    if (!json) return ESP_ERR_NO_MEM;
    cJSON_AddStringToObject(json, "ssid", ROUTER_SSID);
    cJSON_AddStringToObject(json, "ap_ip", "10.42.32.1");
    cJSON_AddNumberToObject(json, "channel", ROUTER_CHANNEL);
    cJSON_AddNumberToObject(json, "clients", clients.num);
    esp_netif_dhcp_status_t dhcp_status = ESP_NETIF_DHCP_INIT;
    esp_netif_dhcps_get_status(ap, &dhcp_status);
    cJSON_AddBoolToObject(json, "dhcp_running", dhcp_status == ESP_NETIF_DHCP_STARTED);
    cJSON *leases = cJSON_AddArrayToObject(json, "client_ips");
    for (int i = 0; leases && i < clients.num; i++) {
        esp_netif_pair_mac_ip_t pair = {0};
        memcpy(pair.mac, clients.sta[i].mac, sizeof(pair.mac));
        if (esp_netif_dhcps_get_clients_by_mac(ap, 1, &pair) == ESP_OK && pair.ip.addr) {
            char client_ip[16];
            snprintf(client_ip, sizeof(client_ip), IPSTR, IP2STR(&pair.ip));
            cJSON_AddItemToArray(leases, cJSON_CreateString(client_ip));
        }
    }
    cJSON_AddBoolToObject(json, "usb_attached", atomic_load(&usb_link));
    cJSON_AddBoolToObject(json, "nat_ready", atomic_load(&nat_ready));
    cJSON_AddBoolToObject(json, "subnet_conflict", atomic_load(&subnet_conflict));
    cJSON_AddStringToObject(json, "usb_ip", addr);
    cJSON_AddStringToObject(json, "usb_gateway", gw);
    cJSON_AddNumberToObject(json, "uptime_seconds", esp_timer_get_time() / 1000000);
    cJSON_AddNumberToObject(json, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(json, "tx_dropped", atomic_load(&tx_dropped));
    cJSON_AddNumberToObject(json, "rx_dropped", atomic_load(&rx_dropped));
    cJSON_AddNumberToObject(json, "dns_queries", atomic_load(&dns_queries));
    cJSON_AddNumberToObject(json, "dns_failures", atomic_load(&dns_failures));
    char *body = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!body) return ESP_ERR_NO_MEM;
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    esp_err_t result = httpd_resp_sendstr(req, body);
    free(body);
    return result;
}

static esp_err_t page_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    return httpd_resp_sendstr(req,
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>ap24 路由器</title><style>body{font:17px system-ui;max-width:650px;margin:40px auto;padding:20px}"
        "pre{background:#eee;padding:20px;border-radius:12px;overflow:auto}</style>"
        "<h1>ap24 · 2.4 GHz</h1><p id=s>正在读取状态…</p><pre id=d></pre>"
        "<p>Mac：系统设置 → 通用 → 共享 → 互联网共享。来源选择 Wi-Fi，目标选择 ap24 USB 网卡。</p>"
        "<script>async function refresh(){try{let r=await fetch('/api/status');let j=await r.json();"
        "document.getElementById('s').textContent=j.nat_ready?'USB 已获得地址，转发已开启（不代表已验证互联网可达）':"
        "j.subnet_conflict?'USB 与热点网段冲突':j.usb_attached?'USB 已连接，等待 Mac 网络共享':'等待 USB 连接';"
        "document.getElementById('d').textContent=JSON.stringify(j,null,2)}catch(e){"
        "document.getElementById('s').textContent='无法连接路由器'} }refresh();setInterval(refresh,5000)</script>");
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    tx_queue = xQueueCreate(24, sizeof(packet_t));
    assert(tx_queue);
    ESP_ERROR_CHECK(esp_event_handler_register(ROUTER_EVENT, ESP_EVENT_ANY_ID, net_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP, net_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_LOST_IP, net_event, NULL));

    ap = esp_netif_create_default_wifi_ap();
    assert(ap);
    esp_netif_dhcps_stop(ap);
    esp_netif_ip_info_t ip = {0};
    inet_pton(AF_INET, "10.42.32.1", &ip.ip.addr);
    ip.gw = ip.ip;
    inet_pton(AF_INET, "255.255.255.0", &ip.netmask.addr);
    ESP_ERROR_CHECK(esp_netif_set_ip_info(ap, &ip));
    esp_netif_dns_info_t dns = { .ip.type = ESP_IPADDR_TYPE_V4, .ip.u_addr.ip4 = ip.ip };
    ESP_ERROR_CHECK(esp_netif_set_dns_info(ap, ESP_NETIF_DNS_MAIN, &dns));
    uint8_t offer_dns = 1;
    ESP_ERROR_CHECK(esp_netif_dhcps_option(ap, ESP_NETIF_OP_SET, ESP_NETIF_DOMAIN_NAME_SERVER, &offer_dns, sizeof(offer_dns)));
    /* stop() above leaves DHCP explicitly STOPPED. Re-arm it before AP_START;
       esp_netif will only auto-start a server whose state is DHCP_INIT. */
    ESP_ERROR_CHECK(esp_netif_dhcps_start(ap));
    wifi_init_config_t wifi_init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    wifi_config_t wifi = { .ap = { .ssid = ROUTER_SSID, .password = ROUTER_PASSWORD,
        .ssid_len = sizeof(ROUTER_SSID) - 1, .channel = ROUTER_CHANNEL,
        .max_connection = ROUTER_MAX_CLIENTS, .authmode = WIFI_AUTH_WPA2_PSK,
        .pmf_cfg = { .required = false } } };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi));
    ESP_ERROR_CHECK(esp_wifi_start());

    esp_netif_inherent_config_t base = ESP_NETIF_INHERENT_DEFAULT_ETH();
    base.if_key = "USB_WAN";
    base.if_desc = "usb";
    base.route_prio = 100;
    esp_netif_config_t config = { .base = &base, .stack = ESP_NETIF_NETSTACK_DEFAULT_ETH };
    wan = esp_netif_new(&config);
    assert(wan);
    esp_netif_driver_ifconfig_t driver = { .handle = wan, .transmit = usb_transmit,
                                         .driver_free_rx_buffer = usb_free_rx };
    ESP_ERROR_CHECK(esp_netif_set_driver_config(wan, &driver));
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_ETH));
    ESP_ERROR_CHECK(esp_netif_set_mac(wan, mac));

    tinyusb_config_t usb_config = TINYUSB_DEFAULT_CONFIG(usb_event);
    usb_config.descriptor.full_speed_config = usb_descriptor;
    ESP_ERROR_CHECK(tinyusb_driver_install(&usb_config));
    tinyusb_net_config_t net_config = { .on_recv_callback = usb_receive };
    /* The CDC NCM descriptor describes the HOST NIC, not our lwIP NIC. */
    memcpy(net_config.mac_addr, mac, 6);
    net_config.mac_addr[0] |= 0x02;
    net_config.mac_addr[5] ^= 0x80;
    ESP_ERROR_CHECK(tinyusb_net_init(&net_config));
    tinyusb_config_cdcacm_t cdc = { .cdc_port = TINYUSB_CDC_ACM_0 };
    ESP_ERROR_CHECK(tinyusb_cdcacm_init(&cdc));
    ESP_ERROR_CHECK(tinyusb_console_init(TINYUSB_CDC_ACM_0));
    assert(xTaskCreate(usb_tx_task, "usb_tx", 4096, NULL, 5, NULL) == pdPASS);
    assert(xTaskCreate(dns_task, "ap_dns", 6144, NULL, 4, NULL) == pdPASS);

    httpd_handle_t http = NULL;
    httpd_config_t http_config = HTTPD_DEFAULT_CONFIG();
    http_config.lru_purge_enable = true;
    ESP_ERROR_CHECK(httpd_start(&http, &http_config));
    httpd_uri_t root = { .uri = "/", .method = HTTP_GET, .handler = page_handler };
    httpd_uri_t status = { .uri = "/api/status", .method = HTTP_GET, .handler = status_handler };
    ESP_ERROR_CHECK(httpd_register_uri_handler(http, &root));
    ESP_ERROR_CHECK(httpd_register_uri_handler(http, &status));
    ESP_LOGI(TAG, "%s ready: 2.4 GHz channel %d, WPA2; status http://10.42.32.1", ROUTER_SSID, ROUTER_CHANNEL);
    for (;;) {
        ESP_LOGI(TAG, "USB=%d NAT=%d heap=%lu drops=%u", atomic_load(&usb_link), atomic_load(&nat_ready),
                 (unsigned long)esp_get_free_heap_size(), atomic_load(&tx_dropped));
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
