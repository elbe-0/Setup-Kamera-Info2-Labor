// XIAO ESP32S3 Sense - capture one JPEG and stream it over USB-CDC,
// base64-encoded between JPEG_BEGIN/JPEG_END markers, repeating every 3 s.
//
// Pin map verified against the Seeed XIAO ESP32S3 Sense schematic.
// Tested against arduino-esp32 v3.x (ESP-IDF v5.5).

#include <Arduino.h>
#include "esp_camera.h"
#include "mbedtls/base64.h"

// --- XIAO ESP32S3 Sense camera pin map (OV2640/OV3660 over DVP) ---
// PWDN/RESET tied off on this board, so software handles power-up.
#define CAM_PIN_PWDN   -1
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK   10
#define CAM_PIN_SIOD   40   // SCCB SDA (I2C-like config bus to the sensor)
#define CAM_PIN_SIOC   39   // SCCB SCL
#define CAM_PIN_D7     48   // 8-bit parallel data bus, MSB
#define CAM_PIN_D6     11
#define CAM_PIN_D5     12
#define CAM_PIN_D4     14
#define CAM_PIN_D3     16
#define CAM_PIN_D2     18
#define CAM_PIN_D1     17
#define CAM_PIN_D0     15   // LSB
#define CAM_PIN_VSYNC  38
#define CAM_PIN_HREF   47
#define CAM_PIN_PCLK   13

// --- Tuning knobs ----------------------------------------------------------
// 76 = the RFC 2045 / MIME base64 line width.  Any wrap-width works as long
// as the host script joins lines back up before decoding.
static const size_t   B64_LINE          = 76;

// 3 s between captures keeps the USB-CDC link from being saturated and gives
// the host script plenty of margin to (re)attach.  Lower for faster bursts.
static const uint32_t CAPTURE_PERIOD_MS = 3000;

// Set true once esp_camera_init succeeds.  loop() refuses to run camera ops
// until this flips, otherwise a failed init produces a wall of "ERR:fb_get"
// every 3 s with no hint of the original cause.
static bool g_camera_ok = false;


static camera_config_t makeCameraConfig() {
    camera_config_t cfg = {};
    cfg.pin_pwdn      = CAM_PIN_PWDN;
    cfg.pin_reset     = CAM_PIN_RESET;
    cfg.pin_xclk      = CAM_PIN_XCLK;
    cfg.pin_sccb_sda  = CAM_PIN_SIOD;
    cfg.pin_sccb_scl  = CAM_PIN_SIOC;
    cfg.pin_d0        = CAM_PIN_D0;
    cfg.pin_d1        = CAM_PIN_D1;
    cfg.pin_d2        = CAM_PIN_D2;
    cfg.pin_d3        = CAM_PIN_D3;
    cfg.pin_d4        = CAM_PIN_D4;
    cfg.pin_d5        = CAM_PIN_D5;
    cfg.pin_d6        = CAM_PIN_D6;
    cfg.pin_d7        = CAM_PIN_D7;
    cfg.pin_vsync     = CAM_PIN_VSYNC;
    cfg.pin_href      = CAM_PIN_HREF;
    cfg.pin_pclk      = CAM_PIN_PCLK;

    // 20 MHz pixel clock.  OV2640/OV3660 spec maximum is 24 MHz, but 20 is
    // the well-tested sweet spot -- higher rates expose signal-integrity
    // problems on flexible PCB ribbons like this board uses.
    cfg.xclk_freq_hz  = 20000000;
    cfg.ledc_timer    = LEDC_TIMER_0;
    cfg.ledc_channel  = LEDC_CHANNEL_0;

    cfg.pixel_format  = PIXFORMAT_JPEG;        // sensor encodes JPEG itself
    cfg.frame_size    = FRAMESIZE_VGA;         // 640x480, ~10-30 KB per frame

    // jpeg_quality: 0-63, lower = better.  10-15 is the typical "good" band;
    // below 8 grows file size aggressively, above 20 starts looking blocky.
    cfg.jpeg_quality  = 12;

    // Double-buffer in PSRAM so one frame can be processed (base64-encoded
    // and sent) while the sensor is already filling the next.  fb_count=1
    // halves memory but blocks the sensor whenever you hold onto a frame.
    cfg.fb_count      = 2;

    // Frame buffers go to PSRAM: a VGA JPEG (~30 KB) plus base64 expansion
    // (~40 KB) easily exceeds the ~300 KB internal SRAM heap budget once
    // you add WiFi, BLE, or any ML model.  PSRAM has 8 MB to spare.
    cfg.fb_location   = CAMERA_FB_IN_PSRAM;

    // GRAB_LATEST: if the consumer is slower than the producer, drop old
    // frames so we always send the freshest one.  GRAB_WHEN_EMPTY would
    // queue them up and serve stale frames.
    cfg.grab_mode     = CAMERA_GRAB_LATEST;
    return cfg;
}


// Encode `fb->buf` as base64 into a PSRAM buffer and stream it over USB-CDC,
// wrapped between JPEG_BEGIN/JPEG_END markers.  Caller still owns `fb`.
static void emitJpeg(const camera_fb_t* fb) {
    // mbedtls trick: a first call with dst=NULL,dlen=0 returns the error
    // MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL (-0x002A) but ALSO writes the
    // required output length to `*needed`.  We deliberately ignore the
    // return value of this sizing call.
    size_t needed = 0;
    mbedtls_base64_encode(nullptr, 0, &needed, fb->buf, fb->len);

    uint8_t* b64 = static_cast<uint8_t*>(
        heap_caps_malloc(needed + 1, MALLOC_CAP_SPIRAM));
    if (!b64) {
        Serial.printf("ERR:alloc need=%u\n", (unsigned)needed);
        return;
    }
    size_t out_len = 0;
    int rc = mbedtls_base64_encode(b64, needed, &out_len, fb->buf, fb->len);
    if (rc != 0) {
        Serial.printf("ERR:base64 rc=%d\n", rc);
        free(b64);
        return;
    }

    Serial.printf("JPEG_BEGIN len=%u w=%u h=%u\n",
                  (unsigned)fb->len, fb->width, fb->height);
    for (size_t i = 0; i < out_len; i += B64_LINE) {
        const size_t n = (out_len - i < B64_LINE) ? (out_len - i) : B64_LINE;
        Serial.write(b64 + i, n);
        Serial.write('\n');
    }
    Serial.println("JPEG_END");
    free(b64);
}


void setup() {
    Serial.begin(115200);
    // Native USB-CDC needs ~1 s to enumerate after reset; this delay makes
    // sure the BOOT line below is visible to host tools that poll lazily.
    delay(1500);

    Serial.println();
    Serial.printf("BOOT psram=%s heap=%u psram_free=%u\n",
                  psramFound() ? "yes" : "no",
                  ESP.getFreeHeap(), ESP.getFreePsram());

    auto cfg = makeCameraConfig();
    esp_err_t err = esp_camera_init(&cfg);
    if (err != ESP_OK) {
        Serial.printf("ERR:cam_init 0x%x - check OV2640 ribbon, power-cycle, "
                      "verify the board is the *Sense* variant\n", err);
        return;     // g_camera_ok stays false; loop() will idle quietly.
    }

    sensor_t* s = esp_camera_sensor_get();
    const uint16_t pid = s ? s->id.PID : 0;
    const char* model =
        pid == OV2640_PID ? "OV2640" :
        pid == OV3660_PID ? "OV3660" :
        pid == OV5640_PID ? "OV5640" :
        "unknown";
    Serial.printf("CAM_OK pid=0x%04x model=%s\n", pid, model);

    g_camera_ok = true;
}


void loop() {
    delay(CAPTURE_PERIOD_MS);

    if (!g_camera_ok) {
        // Print one reminder per minute (every ~20 cycles) instead of
        // spamming an error each loop.  Students will scroll up in the
        // monitor and see the real ERR:cam_init from setup().
        static uint32_t tick = 0;
        if ((tick++ % 20) == 0) {
            Serial.println("STUCK:no-camera - see ERR:cam_init above");
        }
        return;
    }

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("ERR:fb_get");
        return;
    }
    emitJpeg(fb);
    esp_camera_fb_return(fb);
}
