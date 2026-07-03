const base = Module.findBaseAddress("asmsh.exe");
if (base === null) {
  throw new Error("asmsh.exe module base not found");
}

function addr(rva) {
  return base.add(rva - 0x400000);
}

function readCString(ptr) {
  if (ptr.isNull()) return "NULL";
  try {
    return ptr.readCString();
  } catch (_) {
    return ptr.toString();
  }
}

function u8(rva) {
  return addr(rva).readU8();
}

function u32(rva) {
  return addr(rva).readU32();
}

function readPtr(rva) {
  return addr(rva).readPointer();
}

function bytesHex(ptr, size) {
  if (ptr.isNull() || size <= 0) return "";
  try {
    const bytes = new Uint8Array(ptr.readByteArray(size));
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join(" ");
  } catch (_) {
    return "<unreadable>";
  }
}

function currentToken() {
  const p = readPtr(0x471b44);
  const n = u32(0x471b48);
  if (p.isNull() || n <= 0 || n > 256) return "";
  try {
    return p.readUtf8String(n);
  } catch (_) {
    return p.toString();
  }
}

const symbols = {
  parse_command_line_and_options: 0x42b8f0,
  parse_cpu_option: 0x42ce60,
  parse_input_filename_arg: 0x42bb20,
  parse_one_option: 0x42bde0,
  split_statement_head: 0x42fb80,
  read_token_upper: 0x4300f0,
  lookup_instruction_mnemonic: 0x4301a0,
  validate_suffix: 0x42fd50,
  parse_operand_separator_or_suffix: 0x42fee0,
  select_instruction_encoding_form: 0x4300a0,
  read_next_line_or_token: 0x4284e0,
  classify_statement: 0x42fb00,
  emit_object_record: 0x430a30,
  report_error: 0x427850,
  finish_outputs: 0x401fd0,
};

for (const [name, rva] of Object.entries(symbols)) {
  Interceptor.attach(addr(rva), {
    onEnter(args) {
      this.name = name;
      this.ra = this.returnAddress;
      if (name === "parse_command_line_and_options") {
        console.log(`[enter] ${name} argc=${args[0].toInt32()} argv=${args[1]}`);
      } else if (name === "lookup_instruction_mnemonic") {
        this.lookupName = args[0].readUtf8String(12).replace(/\s+$/g, "");
        console.log(`[lookup] mnemonic="${this.lookupName}"`);
      } else if (name === "select_instruction_encoding_form") {
        const entry = readPtr(0x471620);
        const mask = u32(0x471628);
        console.log(`[select-form] entry=${entry} operandMask=0x${mask.toString(16)}`);
      } else if (name === "report_error") {
        console.log(`[error] code=${args[0].toInt32()} arg=${args[1]}`);
      } else if (name === "emit_object_record") {
        this.emitCaller = this.returnAddress;
        const size = args[4].toInt32();
        const outAddrPtr = args[5];
        const outAddr = outAddrPtr.isNull() ? "NULL" : `0x${outAddrPtr.readU32().toString(16)}`;
        const bytes = size <= 32 ? bytesHex(args[3], size) : `<${size} bytes>`;
        const callerRva = this.emitCaller.sub(base).add(0x400000);
        console.log(`[emit] caller=${callerRva} kind0=${args[0].toInt32()} kind1=${args[1].toInt32()} size=${size} outAddr=${outAddr} bytes=${bytes} token="${currentToken()}"`);
      } else {
        console.log(`[enter] ${name}`);
      }
    },
    onLeave(retval) {
      if (this.name === "parse_cpu_option") {
        console.log(`[leave] parse_cpu_option ret=${retval.toInt32()} selected_cpu_id=${u8(0x45b3ea)} active_cpu_id=${u8(0x4574f3)} sh2a_extra_pass=${addr(0x4670e8).readU16()}`);
      } else if (this.name === "read_next_line_or_token" || this.name === "classify_statement") {
        console.log(`[leave] ${this.name} ret=${retval.toInt32()} line_kind=${u8(0x457492)} object_enabled=${u8(0x457493)} pass_flags=${u8(0x457491)} line_no=${u32(0x457494)} token="${currentToken()}"`);
      } else if (this.name === "lookup_instruction_mnemonic") {
        if (retval.isNull()) {
          console.log(`[lookup-ret] mnemonic="${this.lookupName}" entry=NULL`);
        } else {
          const d0 = retval.readU32();
          const d1 = retval.add(4).readU32();
          const d2 = retval.add(8).readU32();
          const suffixPtr = retval.add(12).readPointer();
          const operandPtr = retval.add(16).readPointer();
          const encPtr = retval.add(20).readPointer();
          const cls = retval.add(24).readU8();
          const b25 = retval.add(25).readU8();
          const b26 = retval.add(26).readU8();
          const b27 = retval.add(27).readU8();
          const flags = retval.add(28).readU32();
          console.log(`[lookup-ret] mnemonic="${this.lookupName}" entry=${retval} key=[${d0.toString(16)},${d1.toString(16)},${d2.toString(16)}] suffix=${suffixPtr} operand=${operandPtr} enc=${encPtr} class=${cls} b25=${b25} b26=${b26} b27=${b27} flags=0x${flags.toString(16)}`);
        }
      } else if (this.name === "select_instruction_encoding_form") {
        console.log(`[select-form-ret] form=${readPtr(0x4716ac)} encoder=${readPtr(0x4716b4)} ret=${retval.toInt32()}`);
      } else if (this.name === "finish_outputs") {
        console.log(`[leave] finish_outputs fatal=${u32(0x45b40c)} warning=${u32(0x45b410)} abort_on_warning=${u8(0x45b3ee)}`);
      } else {
        console.log(`[leave] ${this.name} ret=${retval}`);
      }
    },
  });
}

console.log(`[frida] asmsh.exe base=${base}`);
