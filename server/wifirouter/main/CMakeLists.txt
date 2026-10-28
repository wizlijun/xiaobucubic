idf_component_register(SRCS "router.c" INCLUDE_DIRS "." "${CMAKE_CURRENT_BINARY_DIR}"
    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_http_server esp_timer json)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${PROJECT_DIR}/config.local.json" "${PROJECT_DIR}/scripts/configure.py")
execute_process(COMMAND "${PYTHON}" "${PROJECT_DIR}/scripts/configure.py"
    "${PROJECT_DIR}/config.local.json" "${CMAKE_CURRENT_BINARY_DIR}/router_config.h"
    RESULT_VARIABLE CONFIG_RESULT)
if(NOT CONFIG_RESULT EQUAL 0)
    message(FATAL_ERROR "Invalid/missing config.local.json; see README.md")
endif()
