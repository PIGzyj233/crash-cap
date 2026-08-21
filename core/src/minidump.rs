//! Small, bounded reader for the Windows user-mode Minidump streams needed by
//! the Phase 0 inspect contract.
//!
//! This module deliberately does not try to unwind a stack.  It validates the
//! container and extracts stable evidence (system information, exception,
//! thread context descriptors and modules) so that an unwind engine can be
//! added behind the same CLI later.

use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};

const MDMP_SIGNATURE: u32 = 0x504d_444d;
/// Hard input bound for the standalone core. The platform worker enforces the
/// same bound before handing a blob to this process.
pub const MAX_DUMP_BYTES: usize = 256 * 1024 * 1024;
const MAX_STREAMS: u32 = 4096;
const MAX_THREADS: u32 = 65_536;
/// Module records are untrusted input. Keep the initial surface bounded even
/// when a dump advertises a much larger list; the caller receives an explicit
/// warning and the first records are retained for matching.
const MAX_MODULES: u32 = 4096;

const STREAM_THREAD_LIST: u32 = 3;
const STREAM_MODULE_LIST: u32 = 4;
const STREAM_EXCEPTION: u32 = 6;
const STREAM_SYSTEM_INFO: u32 = 7;
const STREAM_THREAD_EX_LIST: u32 = 8;
const STREAM_MISC_INFO: u32 = 15;

const PROCESSOR_ARCHITECTURE_INTEL: u16 = 0;
const PROCESSOR_ARCHITECTURE_AMD64: u16 = 9;
const PROCESSOR_ARCHITECTURE_ARM64: u16 = 12;

// MINIDUMP_SYSTEM_INFO::platform_id values from minidump-common. Windows
// values are 1..=4; Breakpad's Unix/Linux extensions use values such as
// 0x8000 and 0x8201 and must not enter this Windows-only core.
const PLATFORM_WIN32S: u32 = 1;
const PLATFORM_WIN32_WINDOWS: u32 = 2;
const PLATFORM_WIN32_NT: u32 = 3;
const PLATFORM_WIN32_CE: u32 = 4;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InspectFailureKind {
    Unsupported,
    Corrupt,
}

#[derive(Debug, Clone)]
pub struct InspectFailure {
    pub kind: InspectFailureKind,
    pub message: String,
}

impl InspectFailure {
    fn unsupported(message: impl Into<String>) -> Self {
        Self { kind: InspectFailureKind::Unsupported, message: message.into() }
    }

    fn corrupt(message: impl Into<String>) -> Self {
        Self { kind: InspectFailureKind::Corrupt, message: message.into() }
    }
}

impl Display for InspectFailure {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InspectFailure {}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectReport {
    pub schema_version: String,
    pub dump: InspectDump,
    pub process: InspectProcess,
    pub exception: Option<InspectException>,
    pub crash_thread_id: Option<u32>,
    pub threads: Vec<InspectThread>,
    pub modules: Vec<InspectModule>,
    pub warnings: Vec<InspectWarning>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectDump {
    pub kind: String,
    pub size: u64,
    pub signature: String,
    pub number_of_streams: u32,
    pub flags: String,
    pub timestamp: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectProcess {
    pub pid: Option<u32>,
    pub architecture: String,
    pub os: String,
    pub os_version: Option<String>,
    pub platform_id: Option<u32>,
    pub build_number: Option<u32>,
    pub processor_count: Option<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectContext {
    pub size: u32,
    pub rva: u32,
    pub flags: Option<String>,
    pub registers: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectException {
    pub thread_id: u32,
    pub code: String,
    pub name: Option<String>,
    pub flags: String,
    /// Address of the instruction that raised the exception.
    pub address: String,
    /// For access violations, the memory address referenced by the faulting
    /// instruction (ExceptionInformation[1]).
    pub fault_address: Option<String>,
    pub access_type: Option<String>,
    pub parameters: Vec<String>,
    pub context: Option<InspectContext>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectThread {
    pub id: u32,
    pub teb: String,
    pub stack_start: String,
    pub stack_size: u32,
    pub context: Option<InspectContext>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectModule {
    pub code_file: String,
    pub code_id: String,
    pub debug_file: Option<String>,
    pub debug_id: Option<String>,
    pub image_base: String,
    pub image_size: u32,
    pub time_date_stamp: String,
    pub checksum: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectWarning {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Copy)]
struct Location {
    size: u32,
    rva: u32,
}

impl Location {
    fn range<'a>(&self, bytes: &'a [u8], label: &str) -> Result<&'a [u8], InspectFailure> {
        let start = usize::try_from(self.rva)
            .map_err(|_| InspectFailure::corrupt(format!("{label} RVA does not fit usize")))?;
        let size = usize::try_from(self.size)
            .map_err(|_| InspectFailure::corrupt(format!("{label} size does not fit usize")))?;
        let end = start
            .checked_add(size)
            .ok_or_else(|| InspectFailure::corrupt(format!("{label} range overflows")))?;
        bytes
            .get(start..end)
            .ok_or_else(|| InspectFailure::corrupt(format!("{label} points past end of dump")))
    }
}

#[derive(Debug, Clone, Copy)]
struct DirectoryEntry {
    stream_type: u32,
    location: Location,
}

#[derive(Debug, Clone, Copy)]
struct Header {
    number_of_streams: u32,
    stream_directory_rva: u32,
    time_date_stamp: u32,
    flags: u64,
}

pub fn inspect_bytes(bytes: &[u8]) -> Result<InspectReport, InspectFailure> {
    if bytes.len() > MAX_DUMP_BYTES {
        return Err(InspectFailure::unsupported(format!(
            "dump size {} exceeds limit {} bytes",
            bytes.len(),
            MAX_DUMP_BYTES
        )));
    }
    let header = parse_header(bytes)?;
    let directories = parse_directories(bytes, header)?;

    let system_entry = directories
        .iter()
        .find(|entry| entry.stream_type == STREAM_SYSTEM_INFO)
        .ok_or_else(|| InspectFailure::corrupt("missing SystemInfoStream"))?;
    let system = parse_system_info(bytes, system_entry.location)?;

    if !matches!(
        system.platform_id,
        PLATFORM_WIN32S | PLATFORM_WIN32_WINDOWS | PLATFORM_WIN32_NT | PLATFORM_WIN32_CE
    ) {
        return Err(InspectFailure::unsupported(format!(
            "unsupported minidump platform id: 0x{:x}; dmp-core accepts Windows user-mode dumps only",
            system.platform_id
        )));
    }

    let (architecture, supported) = architecture_name(system.processor_architecture);
    if !supported {
        return Err(InspectFailure::unsupported(format!(
            "unsupported minidump architecture: {architecture}"
        )));
    }

    let mut warnings = Vec::new();
    let threads = if let Some(entry) = directories.iter().find(|entry| {
        entry.stream_type == STREAM_THREAD_LIST || entry.stream_type == STREAM_THREAD_EX_LIST
    }) {
        parse_threads(bytes, entry.location, entry.stream_type)?
    } else {
        warnings.push(InspectWarning {
            code: "missing_thread_list".to_owned(),
            message: "the dump has no ThreadListStream or ThreadExListStream".to_owned(),
        });
        Vec::new()
    };

    let modules = if let Some(entry) =
        directories.iter().find(|entry| entry.stream_type == STREAM_MODULE_LIST)
    {
        parse_modules(bytes, entry.location, &mut warnings)?
    } else {
        warnings.push(InspectWarning {
            code: "missing_module_list".to_owned(),
            message: "the dump has no ModuleListStream".to_owned(),
        });
        Vec::new()
    };

    // A WOW64 process can report AMD64 in SystemInfoStream because the dump
    // was collected by a 64-bit host. The module set is stronger target
    // architecture evidence: SysWOW64's x86 ntdll together with the WOW64
    // runtime proves that the user-mode target is x86. Do not infer this from
    // a low image base alone (which is also valid for an x64 image).
    if architecture == "x86_64" && is_wow64_module_set(&modules) {
        return Err(InspectFailure::unsupported(
            "unsupported minidump architecture: WOW64 x86 target detected from SysWOW64 ntdll and WOW64 runtime modules",
        ));
    }

    let exception = if let Some(entry) =
        directories.iter().find(|entry| entry.stream_type == STREAM_EXCEPTION)
    {
        Some(parse_exception(bytes, entry.location)?)
    } else {
        warnings.push(InspectWarning {
            code: "missing_exception_stream".to_owned(),
            message: "the dump has no ExceptionStream; crash type remains unknown".to_owned(),
        });
        None
    };

    let pid = if let Some(entry) =
        directories.iter().find(|entry| entry.stream_type == STREAM_MISC_INFO)
    {
        parse_misc_process_id(bytes, entry.location)?
    } else {
        None
    };
    let process = InspectProcess {
        pid,
        architecture: architecture.to_owned(),
        os: "windows".to_owned(),
        os_version: Some(format!(
            "{}.{}.{}",
            system.major_version, system.minor_version, system.build_number
        )),
        platform_id: Some(system.platform_id),
        build_number: Some(system.build_number),
        processor_count: Some(system.number_of_processors),
    };

    Ok(InspectReport {
        schema_version: "0.1".to_owned(),
        dump: InspectDump {
            kind: "user_minidump".to_owned(),
            size: bytes.len() as u64,
            signature: "MDMP".to_owned(),
            number_of_streams: header.number_of_streams,
            flags: format_hex_u64(header.flags),
            timestamp: minidump_timestamp(header.time_date_stamp),
        },
        process,
        crash_thread_id: exception.as_ref().map(|value| value.thread_id),
        exception,
        threads,
        modules,
        warnings,
    })
}

fn is_wow64_module_set(modules: &[InspectModule]) -> bool {
    let has_syswow64_ntdll = modules.iter().any(|module| {
        let normalized = module.code_file.replace('/', "\\").to_ascii_lowercase();
        normalized.ends_with("\\syswow64\\ntdll.dll")
    });
    let has_wow64_runtime = modules.iter().any(|module| {
        let basename = module
            .code_file
            .rsplit(['\\', '/'])
            .next()
            .unwrap_or(&module.code_file)
            .to_ascii_lowercase();
        matches!(basename.as_str(), "wow64.dll" | "wow64cpu.dll")
    });
    has_syswow64_ntdll && has_wow64_runtime
}

fn parse_header(bytes: &[u8]) -> Result<Header, InspectFailure> {
    if bytes.len() < 4 || read_u32(bytes, 0)? != MDMP_SIGNATURE {
        return Err(InspectFailure::unsupported("input is not a Windows MDMP file"));
    }
    if bytes.len() < 32 {
        return Err(InspectFailure::corrupt("truncated minidump header"));
    }

    let number_of_streams = read_u32(bytes, 8)?;
    if number_of_streams == 0 {
        return Err(InspectFailure::corrupt("minidump has no streams"));
    }
    if number_of_streams > MAX_STREAMS {
        return Err(InspectFailure::corrupt(format!(
            "stream count {number_of_streams} exceeds limit {MAX_STREAMS}"
        )));
    }

    Ok(Header {
        number_of_streams,
        stream_directory_rva: read_u32(bytes, 12)?,
        time_date_stamp: read_u32(bytes, 20)?,
        flags: read_u64(bytes, 24)?,
    })
}

fn minidump_timestamp(value: u32) -> Option<String> {
    if value == 0 {
        return None;
    }
    DateTime::<Utc>::from_timestamp(i64::from(value), 0)
        .map(|timestamp| timestamp.to_rfc3339_opts(SecondsFormat::Secs, true))
}

fn parse_directories(bytes: &[u8], header: Header) -> Result<Vec<DirectoryEntry>, InspectFailure> {
    let directory_size = (header.number_of_streams as usize)
        .checked_mul(12)
        .ok_or_else(|| InspectFailure::corrupt("stream directory size overflows"))?;
    let start = usize::try_from(header.stream_directory_rva)
        .map_err(|_| InspectFailure::corrupt("stream directory RVA does not fit usize"))?;
    let end = start
        .checked_add(directory_size)
        .ok_or_else(|| InspectFailure::corrupt("stream directory range overflows"))?;
    if end > bytes.len() {
        return Err(InspectFailure::corrupt("truncated stream directory"));
    }

    let mut entries = Vec::with_capacity(header.number_of_streams as usize);
    for index in 0..header.number_of_streams as usize {
        let offset = start + index * 12;
        let stream_type = read_u32(bytes, offset)?;
        let location =
            Location { size: read_u32(bytes, offset + 4)?, rva: read_u32(bytes, offset + 8)? };
        // Validate every non-empty location, including unknown streams, so a
        // truncated container is never mistaken for a healthy dump.
        if location.size > 0 {
            let _ = location.range(bytes, &format!("stream {stream_type}"))?;
        }
        entries.push(DirectoryEntry { stream_type, location });
    }
    Ok(entries)
}

#[derive(Debug, Clone, Copy)]
struct SystemInfo {
    processor_architecture: u16,
    number_of_processors: u8,
    major_version: u32,
    minor_version: u32,
    build_number: u32,
    platform_id: u32,
}

fn parse_system_info(bytes: &[u8], location: Location) -> Result<SystemInfo, InspectFailure> {
    let data = location.range(bytes, "SystemInfoStream")?;
    if data.len() < 56 {
        return Err(InspectFailure::corrupt("truncated SystemInfoStream"));
    }
    Ok(SystemInfo {
        processor_architecture: read_u16(data, 0)?,
        number_of_processors: data[6],
        major_version: read_u32(data, 8)?,
        minor_version: read_u32(data, 12)?,
        build_number: read_u32(data, 16)?,
        platform_id: read_u32(data, 20)?,
    })
}

fn architecture_name(value: u16) -> (&'static str, bool) {
    match value {
        PROCESSOR_ARCHITECTURE_AMD64 => ("x86_64", true),
        PROCESSOR_ARCHITECTURE_INTEL => ("x86", false),
        PROCESSOR_ARCHITECTURE_ARM64 => ("arm64", false),
        _ => ("unknown", false),
    }
}

fn parse_threads(
    bytes: &[u8],
    location: Location,
    stream_type: u32,
) -> Result<Vec<InspectThread>, InspectFailure> {
    let data = location.range(bytes, "ThreadListStream")?;
    if data.len() < 4 {
        return Err(InspectFailure::corrupt("truncated thread list"));
    }
    let count = read_u32(data, 0)?;
    if count > MAX_THREADS {
        return Err(InspectFailure::corrupt(format!(
            "thread count {count} exceeds limit {MAX_THREADS}"
        )));
    }
    let entry_size = if stream_type == STREAM_THREAD_EX_LIST {
        // MINIDUMP_THREAD_EX is MINIDUMP_THREAD followed by two location
        // descriptors (backing store and thread stack), 64 bytes total.
        64usize
    } else {
        48usize
    };
    let required = 4usize
        .checked_add((count as usize).saturating_mul(entry_size))
        .ok_or_else(|| InspectFailure::corrupt("thread list size overflows"))?;
    if data.len() < required {
        return Err(InspectFailure::corrupt("truncated thread entries"));
    }

    let mut threads = Vec::with_capacity(count as usize);
    for index in 0..count as usize {
        let offset = 4 + index * entry_size;
        let id = read_u32(data, offset)?;
        let teb = read_u64(data, offset + 16)?;
        let stack_start = read_u64(data, offset + 24)?;
        let stack_size = read_u32(data, offset + 32)?;
        // MINIDUMP_THREAD ends with the ThreadContext location descriptor at
        // offsets 40 (size) and 44 (RVA); offsets 32/36 belong to Stack.
        let context_size = read_u32(data, offset + 40)?;
        let context_rva = read_u32(data, offset + 44)?;
        let context = context_descriptor(bytes, context_size, context_rva, "thread context")?;
        threads.push(InspectThread {
            id,
            teb: format_hex_u64(teb),
            stack_start: format_hex_u64(stack_start),
            stack_size,
            context,
        });
    }
    Ok(threads)
}

fn parse_exception(bytes: &[u8], location: Location) -> Result<InspectException, InspectFailure> {
    let data = location.range(bytes, "ExceptionStream")?;
    if data.len() < 168 {
        return Err(InspectFailure::corrupt("truncated ExceptionStream"));
    }

    let thread_id = read_u32(data, 0)?;
    let code_value = read_u32(data, 8)?;
    let flags_value = read_u32(data, 12)?;
    let address = read_u64(data, 24)?;
    let parameter_count = read_u32(data, 32)?.min(15);
    let mut parameters = Vec::with_capacity(parameter_count as usize);
    for index in 0..parameter_count as usize {
        parameters.push(format_hex_u64(read_u64(data, 40 + index * 8)?));
    }
    let context_size = read_u32(data, 160)?;
    let context_rva = read_u32(data, 164)?;

    let fault_address = if code_value == 0xc000_0005 && parameter_count >= 2 {
        Some(format_hex_u64(read_u64(data, 48)?))
    } else {
        None
    };

    Ok(InspectException {
        thread_id,
        code: format_exception_code(code_value),
        name: exception_name(code_value),
        flags: format_hex_u32(flags_value),
        address: format_hex_u64(address),
        fault_address,
        access_type: access_type(code_value, data, parameter_count),
        parameters,
        context: context_descriptor(bytes, context_size, context_rva, "exception context")?,
    })
}

fn parse_misc_process_id(bytes: &[u8], location: Location) -> Result<Option<u32>, InspectFailure> {
    let data = location.range(bytes, "MiscInfoStream")?;
    if data.len() < 12 {
        return Ok(None);
    }
    Ok(Some(read_u32(data, 8)?))
}

fn exception_name(code: u32) -> Option<String> {
    let name = match code {
        0xc000_0005 => "EXCEPTION_ACCESS_VIOLATION",
        0xc000_001d => "EXCEPTION_ILLEGAL_INSTRUCTION",
        0xc000_0094 => "EXCEPTION_INT_DIVIDE_BY_ZERO",
        0xc000_0096 => "EXCEPTION_PRIV_INSTRUCTION",
        0xc000_00fd => "STATUS_STACK_OVERFLOW",
        0xe06d_7363 => "MSVC_CPP_EXCEPTION",
        0x4000_0015 => "STATUS_FATAL_APP_EXIT",
        _ => return None,
    };
    Some(name.to_owned())
}

fn access_type(code: u32, data: &[u8], parameter_count: u32) -> Option<String> {
    if code != 0xc000_0005 || parameter_count == 0 {
        return None;
    }
    match read_u64(data, 40).ok()? {
        0 => Some("read".to_owned()),
        1 => Some("write".to_owned()),
        8 => Some("execute".to_owned()),
        _ => None,
    }
}

fn context_descriptor(
    bytes: &[u8],
    size: u32,
    rva: u32,
    label: &str,
) -> Result<Option<InspectContext>, InspectFailure> {
    if size == 0 && rva == 0 {
        return Ok(None);
    }
    let location = Location { size, rva };
    let data = location.range(bytes, label)?;
    let flags = if data.len() >= 52 { Some(format_hex_u32(read_u32(data, 48)?)) } else { None };
    let registers = parse_x64_registers(data)?;
    Ok(Some(InspectContext { size, rva, flags, registers }))
}

fn parse_x64_registers(data: &[u8]) -> Result<BTreeMap<String, String>, InspectFailure> {
    // Windows x64 CONTEXT places the general-purpose registers at fixed
    // offsets after the 48-byte home area and control flags. Keep this as
    // evidence only; unwind/trust remains an engine concern.
    const REGISTERS: [(&str, usize); 17] = [
        ("rax", 120),
        ("rcx", 128),
        ("rdx", 136),
        ("rbx", 144),
        ("rsp", 152),
        ("rbp", 160),
        ("rsi", 168),
        ("rdi", 176),
        ("r8", 184),
        ("r9", 192),
        ("r10", 200),
        ("r11", 208),
        ("r12", 216),
        ("r13", 224),
        ("r14", 232),
        ("r15", 240),
        ("rip", 248),
    ];
    let mut registers = BTreeMap::new();
    for (name, offset) in REGISTERS {
        if data.len() < offset + 8 {
            return Ok(BTreeMap::new());
        }
        registers.insert(name.to_owned(), format_hex_u64(read_u64(data, offset)?));
    }
    Ok(registers)
}

fn parse_modules(
    bytes: &[u8],
    location: Location,
    warnings: &mut Vec<InspectWarning>,
) -> Result<Vec<InspectModule>, InspectFailure> {
    let data = location.range(bytes, "ModuleListStream")?;
    if data.len() < 4 {
        return Err(InspectFailure::corrupt("truncated module list"));
    }
    let count = read_u32(data, 0)?;
    let retained_count = count.min(MAX_MODULES);
    if count > MAX_MODULES {
        warnings.push(InspectWarning {
            code: "module_limit_truncated".to_owned(),
            message: format!(
                "module count {count} exceeds limit {MAX_MODULES}; only the first {MAX_MODULES} modules were retained"
            ),
        });
    }
    const MODULE_SIZE: usize = 108;
    let required = 4usize
        .checked_add((retained_count as usize).saturating_mul(MODULE_SIZE))
        .ok_or_else(|| InspectFailure::corrupt("module list size overflows"))?;
    if data.len() < required {
        return Err(InspectFailure::corrupt("truncated module entries"));
    }

    let mut modules = Vec::with_capacity(retained_count as usize);
    for index in 0..retained_count as usize {
        let offset = 4 + index * MODULE_SIZE;
        let image_base = read_u64(data, offset)?;
        let image_size = read_u32(data, offset + 8)?;
        let checksum = read_u32(data, offset + 12)?;
        let timestamp = read_u32(data, offset + 16)?;
        let name_rva = read_u32(data, offset + 20)?;
        let cv_size = read_u32(data, offset + 76)?;
        let cv_rva = read_u32(data, offset + 80)?;
        let code_file =
            read_minidump_string(bytes, name_rva)?.unwrap_or_else(|| "<unnamed>".to_owned());
        let cv = if cv_size > 0 || cv_rva > 0 {
            parse_codeview(bytes, Location { size: cv_size, rva: cv_rva })?
        } else {
            None
        };
        modules.push(InspectModule {
            code_file,
            code_id: format!("{:08X}{:X}", timestamp, image_size),
            debug_file: cv.as_ref().map(|value| value.path.clone()),
            debug_id: cv.as_ref().map(|value| value.debug_id.clone()),
            image_base: format_hex_u64(image_base),
            image_size,
            time_date_stamp: format_hex_u32(timestamp),
            checksum: format_hex_u32(checksum),
        });
    }
    Ok(modules)
}

#[derive(Debug, Clone)]
struct CodeView {
    debug_id: String,
    path: String,
}

fn parse_codeview(bytes: &[u8], location: Location) -> Result<Option<CodeView>, InspectFailure> {
    let data = location.range(bytes, "module CodeView record")?;
    if data.len() < 4 {
        return Err(InspectFailure::corrupt("truncated CodeView record"));
    }
    if &data[0..4] != b"RSDS" {
        return Ok(None);
    }
    if data.len() < 24 {
        return Err(InspectFailure::corrupt("truncated RSDS record"));
    }
    let data1 = read_u32(data, 4)?;
    let data2 = read_u16(data, 8)?;
    let data3 = read_u16(data, 10)?;
    let guid_tail = &data[12..20];
    let age = read_u32(data, 20)?;
    let mut debug_id = format!("{data1:08x}{data2:04x}{data3:04x}");
    debug_id.push_str(&hex::encode(guid_tail));
    debug_id.push_str(&format!("{age:x}"));
    let path_end =
        data[24..].iter().position(|byte| *byte == 0).map(|index| 24 + index).unwrap_or(data.len());
    let path = String::from_utf8_lossy(&data[24..path_end]).to_string();
    Ok(Some(CodeView { debug_id, path }))
}

fn read_minidump_string(bytes: &[u8], rva: u32) -> Result<Option<String>, InspectFailure> {
    if rva == 0 {
        return Ok(None);
    }
    let start = usize::try_from(rva)
        .map_err(|_| InspectFailure::corrupt("module name RVA does not fit usize"))?;
    let length_end = start
        .checked_add(4)
        .ok_or_else(|| InspectFailure::corrupt("minidump string length offset overflows"))?;
    let length_bytes = bytes
        .get(start..length_end)
        .ok_or_else(|| InspectFailure::corrupt("truncated minidump string length"))?;
    let length = u32::from_le_bytes(length_bytes.try_into().expect("length slice is four bytes"));
    let length = usize::try_from(length)
        .map_err(|_| InspectFailure::corrupt("minidump string length does not fit usize"))?;
    if length % 2 != 0 {
        return Err(InspectFailure::corrupt("UTF-16 minidump string has odd byte length"));
    }
    let content_start = start + 4;
    let content_end = content_start
        .checked_add(length)
        .ok_or_else(|| InspectFailure::corrupt("minidump string range overflows"))?;
    let content = bytes
        .get(content_start..content_end)
        .ok_or_else(|| InspectFailure::corrupt("truncated minidump string"))?;
    let mut units = Vec::with_capacity(length / 2);
    for chunk in content.chunks_exact(2) {
        units.push(u16::from_le_bytes([chunk[0], chunk[1]]));
    }
    Ok(Some(String::from_utf16_lossy(&units)))
}

fn format_hex_u32(value: u32) -> String {
    format!("0x{value:08x}")
}

fn format_exception_code(value: u32) -> String {
    format!("0x{value:08X}")
}

fn format_hex_u64(value: u64) -> String {
    format!("0x{value:x}")
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, InspectFailure> {
    let end =
        offset.checked_add(2).ok_or_else(|| InspectFailure::corrupt("integer offset overflows"))?;
    let slice =
        bytes.get(offset..end).ok_or_else(|| InspectFailure::corrupt("truncated integer"))?;
    Ok(u16::from_le_bytes([slice[0], slice[1]]))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, InspectFailure> {
    let end =
        offset.checked_add(4).ok_or_else(|| InspectFailure::corrupt("integer offset overflows"))?;
    let slice =
        bytes.get(offset..end).ok_or_else(|| InspectFailure::corrupt("truncated integer"))?;
    Ok(u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, InspectFailure> {
    let end =
        offset.checked_add(8).ok_or_else(|| InspectFailure::corrupt("integer offset overflows"))?;
    let slice =
        bytes.get(offset..end).ok_or_else(|| InspectFailure::corrupt("truncated integer"))?;
    Ok(u64::from_le_bytes([
        slice[0], slice[1], slice[2], slice[3], slice[4], slice[5], slice[6], slice[7],
    ]))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn put_u16(bytes: &mut [u8], offset: usize, value: u16) {
        bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
    }

    fn put_u32(bytes: &mut [u8], offset: usize, value: u32) {
        bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }

    fn put_u64(bytes: &mut [u8], offset: usize, value: u64) {
        bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }

    #[test]
    fn rejects_non_minidump_as_unsupported() {
        let error = inspect_bytes(b"not a dump").expect_err("must reject");
        assert_eq!(error.kind, InspectFailureKind::Unsupported);
    }

    #[test]
    fn fault_address_is_only_derived_for_access_violation() {
        let mut bytes = vec![0; 168];
        put_u32(&mut bytes, 8, 0xc000_0005);
        put_u32(&mut bytes, 32, 2);
        put_u64(&mut bytes, 48, 0xdead_beef);
        let access_violation = parse_exception(&bytes, Location { size: 168, rva: 0 })
            .expect("access violation exception stream");
        assert_eq!(access_violation.fault_address.as_deref(), Some("0xdeadbeef"));

        put_u32(&mut bytes, 8, 0xc000_00fd);
        let stack_overflow = parse_exception(&bytes, Location { size: 168, rva: 0 })
            .expect("stack overflow exception stream");
        assert_eq!(stack_overflow.name.as_deref(), Some("STATUS_STACK_OVERFLOW"));
        assert_eq!(stack_overflow.fault_address, None);
        assert_eq!(stack_overflow.access_type, None);
    }

    #[test]
    fn rejects_truncated_minidump_as_corrupt() {
        let mut bytes = vec![0; 32];
        put_u32(&mut bytes, 0, MDMP_SIGNATURE);
        put_u32(&mut bytes, 8, 1);
        put_u32(&mut bytes, 12, 32);
        let error = inspect_bytes(&bytes).expect_err("must reject");
        assert_eq!(error.kind, InspectFailureKind::Corrupt);
    }

    #[test]
    fn extracts_system_info_from_minimal_x64_container() {
        let directory_rva = 32usize;
        let system_rva = 44usize;
        let mut bytes = vec![0; system_rva + 56];
        put_u32(&mut bytes, 0, MDMP_SIGNATURE);
        put_u32(&mut bytes, 8, 1);
        put_u32(&mut bytes, 12, directory_rva as u32);
        put_u32(&mut bytes, 20, 1_700_000_000);
        put_u32(&mut bytes, directory_rva, STREAM_SYSTEM_INFO);
        put_u32(&mut bytes, directory_rva + 4, 56);
        put_u32(&mut bytes, directory_rva + 8, system_rva as u32);
        put_u16(&mut bytes, system_rva, PROCESSOR_ARCHITECTURE_AMD64);
        bytes[system_rva + 6] = 8;
        put_u32(&mut bytes, system_rva + 8, 10);
        put_u32(&mut bytes, system_rva + 12, 0);
        put_u32(&mut bytes, system_rva + 16, 22631);
        put_u32(&mut bytes, system_rva + 20, 2);

        let report = inspect_bytes(&bytes).expect("minimal x64 dump should parse");
        assert_eq!(report.process.architecture, "x86_64");
        assert_eq!(report.process.os_version.as_deref(), Some("10.0.22631"));
        assert_eq!(report.dump.timestamp.as_deref(), Some("2023-11-14T22:13:20Z"));
        assert_eq!(report.warnings.len(), 3);
    }

    #[test]
    fn rejects_non_windows_platform_as_unsupported() {
        let directory_rva = 32usize;
        let system_rva = 44usize;
        let mut bytes = vec![0; system_rva + 56];
        put_u32(&mut bytes, 0, MDMP_SIGNATURE);
        put_u32(&mut bytes, 8, 1);
        put_u32(&mut bytes, 12, directory_rva as u32);
        put_u32(&mut bytes, directory_rva, STREAM_SYSTEM_INFO);
        put_u32(&mut bytes, directory_rva + 4, 56);
        put_u32(&mut bytes, directory_rva + 8, system_rva as u32);
        put_u16(&mut bytes, system_rva, PROCESSOR_ARCHITECTURE_AMD64);
        put_u32(&mut bytes, system_rva + 20, 0x8201); // Breakpad Linux

        let error = inspect_bytes(&bytes).expect_err("Linux dump must not enter Windows core");
        assert_eq!(error.kind, InspectFailureKind::Unsupported);
        assert!(error.message.contains("platform id"));
    }

    fn test_module(path: &str) -> InspectModule {
        InspectModule {
            code_file: path.to_owned(),
            code_id: String::new(),
            debug_file: None,
            debug_id: None,
            image_base: "0x0".to_owned(),
            image_size: 0,
            time_date_stamp: "0x00000000".to_owned(),
            checksum: "0x00000000".to_owned(),
        }
    }

    #[test]
    fn detects_wow64_from_syswow64_ntdll_and_runtime_only() {
        assert!(is_wow64_module_set(&[
            test_module(r"C:\Windows\SysWOW64\ntdll.dll"),
            test_module(r"C:\Windows\System32\wow64.dll"),
        ]));
        assert!(is_wow64_module_set(&[
            test_module(r"C:\Windows\SysWOW64\ntdll.dll"),
            test_module(r"C:\Windows\System32\wow64cpu.dll"),
        ]));
        assert!(!is_wow64_module_set(&[test_module(r"C:\Windows\SysWOW64\ntdll.dll")]));
        assert!(!is_wow64_module_set(&[
            test_module(r"C:\Windows\System32\wow64.dll"),
            test_module(r"C:\Windows\System32\ntdll.dll"),
        ]));
        // A low image-base executable without the runtime evidence is not
        // enough to classify an x64 dump as WOW64.
        assert!(!is_wow64_module_set(&[test_module(r"C:\app\target.exe")]));
    }

    #[test]
    fn rejects_real_wow64_fixture_when_available() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../fixtures/p0-d06-non-x64/generated/dump.dmp");
        if !path.is_file() {
            // Generated binaries are intentionally not required in a source
            // checkout. The pure detector test above remains unconditional.
            return;
        }
        let bytes = std::fs::read(path).expect("read real WOW64 fixture");
        let error = inspect_bytes(&bytes).expect_err("WOW64 target must be rejected");
        assert_eq!(error.kind, InspectFailureKind::Unsupported);
        assert!(error.message.contains("WOW64"));
    }

    #[test]
    fn truncates_module_list_at_resource_limit_with_warning() {
        let directory_rva = 32usize;
        let module_rva = 56usize;
        let module_count = MAX_MODULES + 1;
        let module_size = 4 + module_count as usize * 108;
        let system_rva = module_rva + module_size;
        let mut bytes = vec![0; system_rva + 56];
        put_u32(&mut bytes, 0, MDMP_SIGNATURE);
        put_u32(&mut bytes, 8, 2);
        put_u32(&mut bytes, 12, directory_rva as u32);
        put_u32(&mut bytes, directory_rva, STREAM_MODULE_LIST);
        put_u32(&mut bytes, directory_rva + 4, module_size as u32);
        put_u32(&mut bytes, directory_rva + 8, module_rva as u32);
        put_u32(&mut bytes, directory_rva + 12, STREAM_SYSTEM_INFO);
        put_u32(&mut bytes, directory_rva + 16, 56);
        put_u32(&mut bytes, directory_rva + 20, system_rva as u32);
        put_u32(&mut bytes, module_rva, module_count);
        put_u16(&mut bytes, system_rva, PROCESSOR_ARCHITECTURE_AMD64);
        put_u32(&mut bytes, system_rva + 20, PLATFORM_WIN32_NT);

        let report = inspect_bytes(&bytes).expect("bounded module list should parse");
        assert_eq!(report.modules.len(), MAX_MODULES as usize);
        assert!(report.warnings.iter().any(|warning| {
            warning.code == "module_limit_truncated"
                && warning.message.contains("first 4096 modules")
        }));
    }

    #[test]
    fn extracts_thread_context_location_from_thread_stream() {
        let directory_rva = 32usize;
        let thread_rva = 56usize;
        let context_rva = 108usize;
        let context_size = 256usize;
        let system_rva = context_rva + context_size;
        let mut bytes = vec![0; system_rva + 56];
        put_u32(&mut bytes, 0, MDMP_SIGNATURE);
        put_u32(&mut bytes, 8, 2);
        put_u32(&mut bytes, 12, directory_rva as u32);
        put_u32(&mut bytes, directory_rva, STREAM_THREAD_LIST);
        put_u32(&mut bytes, directory_rva + 4, 52);
        put_u32(&mut bytes, directory_rva + 8, thread_rva as u32);
        put_u32(&mut bytes, directory_rva + 12, STREAM_SYSTEM_INFO);
        put_u32(&mut bytes, directory_rva + 16, 56);
        put_u32(&mut bytes, directory_rva + 20, system_rva as u32);

        put_u32(&mut bytes, thread_rva, 1);
        put_u32(&mut bytes, thread_rva + 4, 42);
        put_u64(&mut bytes, thread_rva + 20, 0x7000_0000);
        put_u64(&mut bytes, thread_rva + 28, 0x1000_0000);
        put_u32(&mut bytes, thread_rva + 36, 0x2000);
        put_u32(&mut bytes, thread_rva + 44, context_size as u32);
        put_u32(&mut bytes, thread_rva + 48, context_rva as u32);
        put_u32(&mut bytes, context_rva + 48, 0x0001_0001);
        put_u64(&mut bytes, context_rva + 248, 0x1400_0100_1000);

        put_u16(&mut bytes, system_rva, PROCESSOR_ARCHITECTURE_AMD64);
        bytes[system_rva + 6] = 1;
        put_u32(&mut bytes, system_rva + 8, 10);
        put_u32(&mut bytes, system_rva + 16, 22631);
        put_u32(&mut bytes, system_rva + 20, 2);

        let report = inspect_bytes(&bytes).expect("thread stream should parse");
        let context = report.threads[0].context.as_ref().expect("context descriptor");
        assert_eq!(context.size, context_size as u32);
        assert_eq!(context.rva, context_rva as u32);
        assert_eq!(context.flags.as_deref(), Some("0x00010001"));
        assert_eq!(context.registers.get("rip").map(String::as_str), Some("0x140001001000"));
    }
}
