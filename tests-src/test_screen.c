/*
 * test_screen.c — Full-screen gradient test for the R61523 LCD.
 *
 * Draws a gradient pattern:
 *   - Red increases top-to-bottom
 *   - Green increases left-to-right
 *   - Blue is a diagonal gradient
 *
 * This verifies that:
 *   - The LCD interface (0xB4000000) works
 *   - PRDR RS/DCX selection (0xA405013C bit 4) works
 *   - The R61523 command set (0x2A, 0x2B, 0x2C) works
 *   - RGB565 pixel writing works
 *
 * Build: fxsdk build-cp → test_screen.hh3
 * Run:   python3 run_hh3.py test_screen.hh3 1000000
 */

#include <gint/display.h>
#include <gint/defs/types.h>

/* Direct LCD interface — same as gint's r61523 driver.
 * The ClassPad CP400 uses 320x528 visible area with a 40-column offset.
 */
#define LCD_BASE   0xB4000000
#define PRDR_ADDR  0xA405013C

static volatile uint16_t *const LCD = (volatile uint16_t *)LCD_BASE;
static volatile uint8_t  *const PRDR = (volatile uint8_t  *)PRDR_ADDR;

static void lcd_cmd(uint16_t cmd)
{
    *PRDR &= 0xEF;   /* RS = 0 (command) */
    *LCD = cmd;
    *PRDR |= 0x10;   /* RS = 1 (data) */
}

static void lcd_data(uint16_t data)
{
    *LCD = data;
}

void screen_main(void)
{
    int x, y;

    /* Set column address: 0..319 (with 40-column offset for CP400) */
    lcd_cmd(0x2A);  /* SET_COLUMN_ADDRESS */
    lcd_data(0); lcd_data(40);
    lcd_data(0); lcd_data(40 + 319);

    /* Set page address: 0..527 */
    lcd_cmd(0x2B);  /* SET_PAGE_ADDRESS */
    lcd_data(0); lcd_data(0);
    lcd_data(0); lcd_data(527);

    /* Write memory start */
    lcd_cmd(0x2C);  /* WRITE_MEMORY_START */

    /* Draw gradient */
    for (y = 0; y < 528; y++) {
        for (x = 0; x < 320; x++) {
            uint16_t r = (y * 31) / 528;
            uint16_t g = (x * 63) / 320;
            uint16_t b = ((x + y) * 31) / (320 + 528);
            uint16_t rgb565 = (r << 11) | (g << 5) | b;
            lcd_data(rgb565);
        }
    }

    /* Loop forever (keep the display on) */
    while (1) {
        __asm__ volatile ("sleep");
    }
}

/* Entry point — gint calls this after hhk3_entry sets up syscalls.
 * We bypass gint's display driver and write directly to the LCD
 * interface so we don't depend on gint's driver initialization.
 */
int start(int load_type, uint32_t *load_info)
{
    (void)load_type;
    (void)load_info;
    screen_main();
    return 0;
}
