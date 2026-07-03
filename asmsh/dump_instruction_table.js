const base = Module.findBaseAddress("asmsh.exe");
if (base === null) throw new Error("asmsh.exe module base not found");

function addr(rva) {
  return base.add(rva - 0x400000);
}

function readMnemonic(entry) {
  let s = "";
  for (let i = 0; i < 3; i++) {
    const v = entry.add(i * 4).readU32();
    s += String.fromCharCode((v >>> 24) & 0xff);
    s += String.fromCharCode((v >>> 16) & 0xff);
    s += String.fromCharCode((v >>> 8) & 0xff);
    s += String.fromCharCode(v & 0xff);
  }
  return s.replace(/\s+$/g, "");
}

function readRawKey(entry) {
  let s = "";
  for (let i = 0; i < 12; i++) {
    const c = entry.add(i).readU8();
    s += c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : ".";
  }
  return s.replace(/\s+$/g, "");
}

let dumpedAfterLookup = false;

function dumpTable(tag) {
  const count = addr(0x4547c2).readU16();
  const rows = [];
  for (let i = 0; i < count; i++) {
    const e = addr(0x4547c8 + i * 32);
    rows.push({
      index: i,
      entry: e.toString(),
      raw_key: readRawKey(e),
      mnemonic: readMnemonic(e),
      suffix: e.add(12).readPointer().toString(),
      operand: e.add(16).readPointer().toString(),
      enc: e.add(20).readPointer().toString(),
      cpu_mask: e.add(24).readU32(),
      secondary_mask: e.add(28).readU32(),
    });
  }
  console.log(`[table-json:${tag}] ${JSON.stringify({ count, rows })}`);
}

Interceptor.attach(addr(0x4301a0), {
  onLeave() {
    if (!dumpedAfterLookup) {
      dumpedAfterLookup = true;
      dumpTable("after-first-lookup");
    }
  },
});

Interceptor.attach(addr(0x401fd0), {
  onEnter() {
    dumpTable("finish");
  },
});

console.log(`[frida] dump_instruction_table base=${base}`);
