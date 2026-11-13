idf_component_register(SRCS "router.c" "display.c" "board.c" "qualia_expander.c" "app_runtime.c" "app_model.c" "app_ui.c" "scaled_font.c" INCLUDE_DIRS "." "${CMAKE_CURRENT_BINARY_DIR}"
    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_http_server esp_timer json esp_lcd esp_psram
        spiffs esp_http_client mbedtls esp_driver_i2c esp_driver_ledc esp_io_expander)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${PROJECT_DIR}/config.local.json" "${PROJECT_DIR}/scripts/configure.py")
execute_process(COMMAND "${PYTHON}" "${PROJECT_DIR}/scripts/configure.py"
    "${PROJECT_DIR}/config.local.json" "${CMAKE_CURRENT_BINARY_DIR}/router_config.h"
    RESULT_VARIABLE CONFIG_RESULT)
if(NOT CONFIG_RESULT EQUAL 0)
    message(FATAL_ERROR "Invalid/missing config.local.json; see README.md")
endif()

if(CONFIG_APP_PNG_RGB565_DITHER)
    target_sources(${COMPONENT_LIB} PRIVATE "image_quantize.c" "png_quantize.c")
    target_link_libraries(${COMPONENT_LIB} INTERFACE
        "-Wl,--wrap=lodepng_decode32" "-Wl,-u,__wrap_lodepng_decode32")
endif()

set(APP_SOURCE "${PROJECT_DIR}/../../apps/xiaobucubic/package")
file(GLOB_RECURSE APP_INPUTS CONFIGURE_DEPENDS "${APP_SOURCE}/*")
file(GLOB SCREEN_FONTS CONFIGURE_DEPENDS "${PROJECT_DIR}/assets/fonts/*")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    ${APP_INPUTS} ${SCREEN_FONTS} "${PROJECT_DIR}/app.local.json" "${PROJECT_DIR}/scripts/prepare_app.py")
execute_process(COMMAND "${PYTHON}" "${PROJECT_DIR}/scripts/prepare_app.py"
    "${APP_SOURCE}" "${PROJECT_DIR}/app.local.json" "${CMAKE_BINARY_DIR}/app_assets"
    RESULT_VARIABLE APP_CONFIG_RESULT)
if(NOT APP_CONFIG_RESULT EQUAL 0)
    message(FATAL_ERROR "Invalid/missing app.local.json; see app.example.json")
endif()
spiffs_create_partition_image(app_assets "${CMAKE_BINARY_DIR}/app_assets" FLASH_IN_PROJECT)
idf_component_get_property(JSON_LIB json COMPONENT_LIB)
target_compile_definitions(${JSON_LIB} PRIVATE CJSON_NESTING_LIMIT=32)
idf_component_get_property(LVGL_LIB lvgl__lvgl COMPONENT_LIB)
target_include_directories(${LVGL_LIB} PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_compile_definitions(${LVGL_LIB} PUBLIC
    LV_MEM_CUSTOM_INCLUDE="app_memory.h"
    LV_MEM_CUSTOM_ALLOC=app_lv_malloc LV_MEM_CUSTOM_REALLOC=app_lv_realloc LV_MEM_CUSTOM_FREE=app_lv_free)
if(CONFIG_BOARD_QUALIA_5800 AND CONFIG_LV_DITHER_GRADIENT)
    # LVGL 8.3.11's ordered vertical dither adds +/-32 to 8-bit channels.
    # Replace only that function with adjacent-RGB565-level quantization.
    target_sources(${COMPONENT_LIB} PRIVATE "qualia_dither.c")
    target_link_libraries(${COMPONENT_LIB} INTERFACE
        "-Wl,--wrap=lv_dither_ordered_ver" "-Wl,-u,__wrap_lv_dither_ordered_ver")
endif()
