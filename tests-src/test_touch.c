/*
 * test_touch.c — Touchscreen test addin for RuK.
 *
 * Draws a crosshair at the current touch position.  Verifies that:
 *   - PRDR touch detect (0xA405013C bit 5) works
 *   - I2C register read from FT6206 (register 0x84) returns data
 *   - Touch coordinates map to screen pixels
 *
 * The touch data format (from gint's touch driver):
 *   Register 0x84, 16 bytes:
 *     offset 0:  x1 (16-bit BE) — first touch X (raw ADC value)
 *     offset 2:  y1 (16-bit BE) — first touch Y (raw ADC value)
 *     offset 4:  z1 (16-bit BE) — first touch pressure
 *     offset 6:  x2 (16-bit BE) — second touch X (delta)
 *     offset 8:  y2 (16-bit BE) — second touch Y (delta)
 *     offset 10: z2 (16-bit BE) — second touch pressure
 *     offset 12: gh (16-bit BE) — gesture
 *     offset 14: dm (16-bit BE) — display mode
 *
 * gint's conversion: adconv->x1 = adraw->x1 >> 4
 * Then calibration: dots->x1 = ((adconv->x1 - x_base) * 256) / x_div
 *
 * Build: fxsdk build-cp → test_touch.hh3
 * Run:   python3 run_hh3.py test_touch.hh3 1000000
 */

#include <gint/defs/types.h>

/* Direct hardware access — no gint driver dependency */
#define LCD_BASE   0xB4000000
#define PRDR_ADDR  0xA405013C
#define I2C_BASE   0xA4470000

static volatile uint16_t *const LCD = (volatile uint16_t *)LCD_BASE;
static volatile uint8_t  *const PRDR = (volatile uint8_t  *)PRDR_ADDR;

/* I2C registers */
static volatile uint8_t *const ICDR = (volatile uint8_t *)(I2C_BASE + 0x00);
static volatile uint8_t *const ICCR = (volatile uint8_t *)(I2C_BASE + 0x04);
static volatile uint8_t *const ICSR = (volatile uint8_t *)(I2C_BASE + 0x08);
static volatile uint8_t *const ICIC = (volatile uint8_t *)(I2C_BASE + 0x0C);
static volatile uint8_t *const ICCL = (volatile uint8_t *)(I2C_BASE + 0x10);
static volatile uint8_t *const ICCH = (volatile uint8_t *)(I2C_BASE + 0x14);

/* I2C register bits */
#define ICCR_ICE   0x01
#define ICSR_BUSY  0x08
#define ICSR_TACK  0x20
#define ICSR_DTE   0x80

/* FT6206 I2C slave address (7-bit, shifted left for transmission) */
#define FT6206_ADDR  0x38

/* gint calibration defaults */
#define X_BASE  0x20b
#define X_DIV   0x9b6
#define Y_BASE  0x0f4
#define Y_DIV   0x66f

/* ---- LCD helpers (same as test_screen.c) ---- */

static void lcd_cmd(uint16_t cmd)
{
    *PRDR &= 0xEF;
    *LCD = cmd;
    *PRDR |= 0x10;
}

static void lcd_data(uint16_t data)
{
    *LCD = data;
}

static void lcd_clear(uint16_t color)
{
    int x, y;
    lcd_cmd(0x2A); lcd_data(0); lcd_data(40); lcd_data(0); lcd_data(40+319);
    lcd_cmd(0x2B); lcd_data(0); lcd_data(0); lcd_data(0); lcd_data(527);
    lcd_cmd(0x2C);
    for (y = 0; y < 528; y++)
        for (x = 0; x < 320; x++)
            lcd_data(color);
}

static void lcd_pixel(int x, int y, uint16_t color)
{
    lcd_cmd(0x2A);
    lcd_data(0); lcd_data(40 + x);
    lcd_data(0); lcd_data(40 + x);
    lcd_cmd(0x2B);
    lcd_data(0); lcd_data(y);
    lcd_data(0); lcd_data(y);
    lcd_cmd(0x2C);
    lcd_data(color);
}

static void draw_crosshair(int cx, int cy, uint16_t color)
{
    int x, y;
    /* Horizontal line */
    for (x = cx - 10; x <= cx + 10; x++) {
        if (x >= 0 && x < 320)
            lcd_pixel(x, cy, color);
    }
    /* Vertical line */
    for (y = cy - 10; y <= cy + 10; y++) {
        if (y >= 0 && y < 528)
            lcd_pixel(cx, y, color);
    }
    /* Center dot */
    lcd_pixel(cx, cy, 0xFFFF);
}

/* ---- I2C helpers (simplified from gint's i2c.c) ---- */

static void i2c_wait_dte(void)
{
    while (!(*ICSR & ICSR_DTE))
        __asm__ volatile ("sleep");
}

static int i2c_reg_read(uint8_t reg, void *buffer, int size)
{
    uint8_t *buf = (uint8_t *)buffer;
    int i;

    /* Enable I2C */
    *ICCR = ICCR_ICE;
    while (*ICSR & ICSR_BUSY) {}

    /* Set clock */
    *ICCL = 0x29;
    *ICCH = 0x22;

    /* Start condition + write slave address */
    *ICIC = 0xF0;  /* ALE | TACKE | WAITE | DTEE */
    *ICCR = 0x94;  /* start */

    /* Send slave address (write) */
    *ICDR = (FT6206_ADDR << 1) | 0;  /* write */
    i2c_wait_dte();

    /* Send register number */
    *ICDR = reg;
    i2c_wait_dte();

    /* Repeated start + slave address (read) */
    *ICCR = 0x94;  /* restart */
    *ICDR = (FT6206_ADDR << 1) | 1;  /* read */
    i2c_wait_dte();

    /* Read data bytes */
    for (i = 0; i < size; i++) {
        i2c_wait_dte();
        buf[i] = *ICDR;
    }

    /* Stop condition */
    *ICCR = 0x90;  /* stop */

    return 0;
}

/* ---- Touch reading (from gint's touch.c) ---- */

static int touch_read_raw(uint16_t *x1, uint16_t *y1, uint16_t *z1)
{
    uint8_t buf[16];

    /* Check PRDR bit 5: 0 = touch pending */
    if (*PRDR & 0x20)
        return 0;  /* no touch */

    /* Read 16 bytes from FT6206 register 0x84 */
    i2c_reg_read(0x84, buf, 16);

    /* Parse big-endian 16-bit values */
    *x1 = (buf[0] << 8) | buf[1];
    *y1 = (buf[2] << 8) | buf[3];
    *z1 = (buf[4] << 8) | buf[5];

    return 1;  /* touch detected */
}

static int touch_to_screen(int raw_x, int raw_y)
{
    /* gint conversion: raw >> 4, then calibrate */
    int conv_x = raw_x >> 4;
    int conv_y = raw_y >> 4;

    /* Calibration: dots->x = ((conv - base) * 256) / div */
    int screen_x = ((conv_x - X_BASE) * 256) / X_DIV;
    int screen_y = ((conv_y - Y_BASE) * 256) / Y_DIV;

    /* Clamp to screen bounds */
    if (screen_x < 0) screen_x = 0;
    if (screen_x >= 320) screen_x = 319;
    if (screen_y < 0) screen_y = 0;
    if (screen_y >= 528) screen_y = 527;

    return screen_x | (screen_y << 16);
}

/* ---- Main ---- */

int start(int load_type, uint32_t *load_info)
{
    (void)load_type;
    (void)load_info;

    /* Clear screen to black */
    lcd_clear(0x0000);

    int last_x = -1, last_y = -1;

    /* Main loop: poll touch and draw crosshair */
    while (1) {
        uint16_t x1, y1, z1;
        if (touch_read_raw(&x1, &y1, &z1)) {
            int pos = touch_to_screen(x1, y1);
            int sx = pos & 0xFFFF;
            int sy = (pos >> 16) & 0xFFFF;

            /* Erase old crosshair (draw black) */
            if (last_x >= 0)
                draw_crosshair(last_x, last_y, 0x0000);

            /* Draw new crosshair (white) */
            draw_crosshair(sx, sy, 0xFFFF);
            last_x = sx;
            last_y = sy;
        }
        __asm__ volatile ("sleep");
    }

    return 0;
}
