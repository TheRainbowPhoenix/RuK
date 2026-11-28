"""SH7305 battery ADC, with synchronous conversions as in clemu."""

ADC_BASE = 0xA4610080
ADC_SIZE = 0x10


class ADC:
    def __init__(self):
        self.voltages = [1.65, 1.65, 2.9, 0.4]
        self.results = [0] * 4
        self.csr = [0, 0]
        self.shadow = [0, 0]
        self.ust = 0
        self.pctl = 0
        self.on_irq = None
        self._irq = False

    def set_channel_voltage(self, channel, volts):
        if not 0 <= channel < 4:
            raise ValueError('ADC channel must be in 0..3')
        self.voltages[channel] = max(0.0, min(3.3, volts))

    def _update_irq(self):
        active = any((value & 0xc000) == 0xc000 for value in self.csr)
        if active and not self._irq and self.on_irq:
            self.on_irq(0x560)
        self._irq = active

    def read16(self, addr):
        offset = addr - ADC_BASE
        if 0 <= offset < 8 and not offset & 1:
            return self.results[offset // 2]
        if offset in (8, 10):
            unit = (offset - 8) // 2
            self.shadow[unit] = self.csr[unit]
            return self.csr[unit]
        return {12: self.ust, 14: self.pctl}.get(offset, 0)

    def write16(self, addr, value):
        offset = addr - ADC_BASE
        if offset in (8, 10):
            unit = (offset - 8) // 2
            old = self.csr[unit]
            flag = old & 0x8000
            if not value & 0x8000 and self.shadow[unit] & 0x8000:
                flag = 0
            self.csr[unit] = flag | (value & (0x70f3 if unit == 0 else 0x63ff))
            selected = bool(self.ust & 0x8000) == bool(unit)
            if selected and not old & 0x2000 and value & 0x2000:
                ch = value & 15
                channels = range(4) if unit and value & 0xc0 == 0xc0 else (range(ch + 1) if not unit and value & 0x10 else [ch])
                for ch in channels:
                    if ch < 4:
                        self.results[ch] = min(1023, int(self.voltages[ch] / 3.3 * 1024 + 0.5)) << 6
                self.csr[unit] |= 0x8000
            if selected:
                self._update_irq()
        elif offset == 12:
            self.ust = value & 0x8001
            if value & 1:
                self.csr = [0, 0]
                self.pctl = 0
            self._update_irq()
        elif offset == 14:
            self.pctl = value & 0xf0ff

    def read8(self, addr):
        raise ValueError('ADC requires 16-bit accesses')

    read32 = read8

    def write8(self, addr, value):
        raise ValueError('ADC requires 16-bit accesses')

    write32 = write8
