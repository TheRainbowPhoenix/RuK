/*
 * test_hello.c — Minimal "Hello World" test addin for RuK.
 *
 * Draws a simple pattern to the LCD to verify the basic hh3 loading
 * pipeline:
 *   - ELF loading (PT_LOAD segments)
 *   - Symbol table setup (HHK_SYMBOL_TABLE envp)
 *   - Entry point (hhk3_entry -> start)
 *   - LCD interface (0xB4000000)
 *
 * This is the simplest possible test — no touchscreen, no I2C, just
 * direct LCD writes.
 *
 * Build: fxsdk build-cp → test_hello.hh3
 * Run:   python3 run_hh3.py test_hello.hh3 1000000
 */

#include <gint/defs/types.h>

#define LCD_BASE   0xB4000000
#define PRDR_ADDR  0xA405013C

static volatile uint16_t *const LCD = (volatile uint16_t *)LCD_BASE;
static volatile uint8_t  *const PRDR = (volatile uint8_t  *)PRDR_ADDR;

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

int start(int load_type, uint32_t *load_info)
{
    (void)load_type;
    (void)load_info;
    int x, y;

    /* Set full-screen write window */
    lcd_cmd(0x2A); lcd_data(0); lcd_data(40); lcd_data(0); lcd_data(40+319);
    lcd_cmd(0x2B); lcd_data(0); lcd_data(0); lcd_data(0); lcd_data(527);
    lcd_cmd(0x2C);

    /* Draw color bars: red, green, blue, white, black */
    uint16_t colors[] = {0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000};
    int bar_height = 528 / 5;

    for (y = 0; y < 528; y++) {
        uint16_t color = colors[y / bar_height];
        for (x = 0; x < 320; x++) {
            lcd_data(color);
        }
    }

    /* Loop forever */
    while (1) {
        __asm__ volatile ("sleep");
    }

    return 0;
}
