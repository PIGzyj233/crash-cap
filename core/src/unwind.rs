//! Official rust-minidump stack walking for the CORE analysis path.
//!
//! `minidump` parses the container and `minidump-processor` performs the
//! architecture-specific walk.  This module intentionally exposes a small,
//! owned representation so the canonical normalizer is not coupled to the
//! engine's unstable native structs.  In particular, the `trust` value is
//! copied from rust-minidump's `FrameTrust` rather than inferred from the
//! presence of a frame.

use futures_executor::block_on;
use minidump::{
    Minidump, MinidumpException, MinidumpMiscInfo, MinidumpModuleList, MinidumpSystemInfo,
    MinidumpThreadList, Module,
};
use minidump_processor::{process_minidump, ProcessError};
use minidump_unwind::symbols::debuginfo::DebugInfoSymbolProvider;
use minidump_unwind::SystemInfo;
use minidump_unwind::{simple_symbol_supplier, walk_stack, CallStack, FrameTrust, Symbolizer};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnwindReport {
    pub threads: Vec<UnwindThread>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnwindThread {
    pub id: u32,
    pub frames: Vec<UnwindFrame>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnwindFrame {
    pub instruction: u64,
    pub resume_address: u64,
    pub module: Option<UnwindModule>,
    pub function: Option<String>,
    pub file: Option<String>,
    pub line: Option<u32>,
    pub trust: String,
    pub inline: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnwindModule {
    pub code_file: String,
    pub code_id: Option<String>,
    pub debug_file: Option<String>,
    pub debug_id: Option<String>,
    pub image_base: u64,
    pub image_size: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum UnwindError {
    #[error("rust-minidump could not parse the dump: {0}")]
    Parse(#[from] minidump::Error),
    #[error("rust-minidump could not unwind the dump: {0}")]
    Process(#[from] ProcessError),
    #[error("rust-minidump is missing a required stream: {0}")]
    MissingStream(&'static str),
}

/// Unwind all threads with rust-minidump.  `symbol_paths` are optional
/// Breakpad symbol roots; an empty list is valid and still yields context,
/// frame-pointer and stack-scan evidence where the dump contains enough data.
pub fn unwind_bytes(bytes: &[u8], symbol_paths: &[PathBuf]) -> Result<UnwindReport, UnwindError> {
    let dump = Minidump::read(bytes.to_vec())?;
    let supplier = simple_symbol_supplier(symbol_paths.to_vec());
    let symbolizer = Symbolizer::new(supplier);
    let state = block_on(process_minidump(&dump, &symbolizer))?;

    let threads = state
        .threads
        .iter()
        .map(|thread| UnwindThread {
            id: thread.thread_id,
            frames: thread
                .frames
                .iter()
                .map(|frame| UnwindFrame {
                    instruction: frame.instruction,
                    resume_address: frame.resume_address,
                    module: frame.module.as_ref().map(module_info),
                    function: frame.function_name.clone(),
                    file: frame.source_file_name.clone(),
                    line: frame.source_line,
                    trust: trust_name(frame.trust),
                    inline: !frame.inlines.is_empty(),
                })
                .collect(),
        })
        .collect();

    Ok(UnwindReport { threads })
}

/// Unwind using rust-minidump's local binary provider.  `module_paths` maps a
/// verified dump `code_id` to its PE path.  The module list is cloned and
/// patched before creating the provider, so Windows absolute paths embedded in
/// a dump are never dereferenced on the Linux worker.
pub fn unwind_bytes_with_modules(
    bytes: &[u8],
    module_paths: &BTreeMap<String, PathBuf>,
) -> Result<UnwindReport, UnwindError> {
    let dump = Minidump::read(bytes.to_vec())?;
    let system = dump
        .get_stream::<MinidumpSystemInfo>()
        .map_err(|_| UnwindError::MissingStream("SystemInfoStream"))?;
    let original_modules = dump
        .get_stream::<MinidumpModuleList>()
        .map_err(|_| UnwindError::MissingStream("ModuleListStream"))?;
    let mut patched = original_modules.iter().cloned().collect::<Vec<_>>();
    for module in &mut patched {
        let code_id = module.code_identifier().map(|id| id.to_string());
        if let Some(path) = code_id.and_then(|id| {
            module_paths.get(&id).or_else(|| {
                module_paths
                    .iter()
                    .find(|(key, _)| key.eq_ignore_ascii_case(&id))
                    .map(|(_, path)| path)
            })
        }) {
            module.name = path.display().to_string();
        }
    }
    let modules = MinidumpModuleList::from_modules(patched);
    let provider =
        block_on(DebugInfoSymbolProvider::builder().symbols(false).build(&system, &modules));
    let unwind_system = SystemInfo {
        os: system.os,
        os_version: Some(format!(
            "{}.{}.{}",
            system.raw.major_version, system.raw.minor_version, system.raw.build_number
        )),
        os_build: system.csd_version().map(|value| value.into_owned()),
        cpu: system.cpu,
        cpu_info: system.cpu_info().map(|value| value.into_owned()),
        cpu_microcode_version: None,
        cpu_count: system.raw.number_of_processors as usize,
    };
    let threads = dump
        .get_stream::<MinidumpThreadList>()
        .map_err(|_| UnwindError::MissingStream("ThreadListStream"))?;
    let exception = dump.get_stream::<MinidumpException>().ok();
    let misc = dump.get_stream::<MinidumpMiscInfo>().ok();
    let memory = dump.get_memory().unwrap_or_default();
    let exception_thread = exception.as_ref().map(MinidumpException::get_crashing_thread_id);
    let mut outputs = Vec::with_capacity(threads.threads.len());
    for (index, thread) in threads.threads.iter().enumerate() {
        let thread_context = thread.context(&system, misc.as_ref());
        let exception_context = if exception_thread == Some(thread.raw.thread_id) {
            exception.as_ref().and_then(|value| value.context(&system, misc.as_ref()))
        } else {
            None
        };
        let Some(context) = exception_context.as_deref().or(thread_context.as_deref()) else {
            outputs.push(UnwindThread { id: thread.raw.thread_id, frames: Vec::new() });
            continue;
        };
        let mut stack = CallStack::with_context(context.clone());
        stack.thread_id = thread.raw.thread_id;
        let stack_memory = thread.stack_memory(&memory);
        block_on(walk_stack(
            index,
            (),
            &mut stack,
            stack_memory,
            &modules,
            &unwind_system,
            &provider,
        ));
        outputs.push(UnwindThread {
            id: thread.raw.thread_id,
            frames: stack
                .frames
                .iter()
                .map(|frame| UnwindFrame {
                    instruction: frame.instruction,
                    resume_address: frame.resume_address,
                    module: frame.module.as_ref().map(module_info),
                    function: frame.function_name.clone(),
                    file: frame.source_file_name.clone(),
                    line: frame.source_line,
                    trust: trust_name(frame.trust),
                    inline: !frame.inlines.is_empty(),
                })
                .collect(),
        });
    }
    Ok(UnwindReport { threads: outputs })
}

fn module_info(module: &minidump::MinidumpModule) -> UnwindModule {
    UnwindModule {
        code_file: module.code_file().into_owned(),
        code_id: module.code_identifier().map(|id| id.to_string()),
        debug_file: module.debug_file().map(|file| file.into_owned()),
        debug_id: module.debug_identifier().map(|id| id.to_string()),
        image_base: module.base_address(),
        image_size: module.size(),
    }
}

fn trust_name(trust: FrameTrust) -> String {
    match trust {
        FrameTrust::Context => "context",
        FrameTrust::CallFrameInfo | FrameTrust::CfiScan => "cfi",
        FrameTrust::FramePointer => "frame_pointer",
        FrameTrust::Scan => "scan",
        FrameTrust::PreWalked | FrameTrust::None => "unknown",
    }
    .to_owned()
}

#[cfg(test)]
mod tests {
    use super::trust_name;
    use minidump_unwind::FrameTrust;

    #[test]
    fn official_trust_values_map_to_contract_values() {
        assert_eq!(trust_name(FrameTrust::Context), "context");
        assert_eq!(trust_name(FrameTrust::CallFrameInfo), "cfi");
        assert_eq!(trust_name(FrameTrust::FramePointer), "frame_pointer");
        assert_eq!(trust_name(FrameTrust::Scan), "scan");
        assert_eq!(trust_name(FrameTrust::None), "unknown");
    }
}
