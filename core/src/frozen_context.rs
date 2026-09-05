//! Immutable Run v3 verification before native analysis or source requests.
//! Schemas are embedded; input never selects a schema URI or network retriever.

use crate::canonical::{sha256_hex, NORMALIZATION_VERSION};
use crate::canonical_v11::{
    EvidenceError, FrozenInputs, FrozenModule, FrozenSelection, ModuleIdentity, SourceOutcome,
    SymbolResolution, GROUPING_VERSION,
};
use crate::minidump::InspectReport;
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::PathBuf;

pub const INSPECTOR_VERSION: &str = "inspect-v0.1";
pub const MAX_INPUT_BYTES: usize = 64 * 1024 * 1024;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const RUN_SCHEMA: &str =
    include_str!("../../contracts/drafts/qa-symbol-import/analysis-run-v3.schema.json");
const MANIFEST_SCHEMA: &str =
    include_str!("../../contracts/drafts/qa-symbol-import/resolution-manifest-v1.schema.json");

fn require(ok: bool, reason: &str) -> Result<(), EvidenceError> {
    if ok {
        Ok(())
    } else {
        Err(EvidenceError(reason.to_owned()))
    }
}

/// Pins observed/configured by the deployment owner, not read from the Run.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnginePins {
    pub core_image_digest: String,
    pub symbolicator_image_digest: String,
    pub symbolicator_version: String,
}

/// Assignment read from the immutable platform Run record, independently of
/// the staged Run JSON. This binds non-semantic facts and the execution owner.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunAssignment {
    pub run_id: String,
    pub occurrence_id: String,
    pub workspace_id: String,
    pub object_sha256: String,
}

#[derive(Debug)]
pub struct VerifiedRun {
    run: Value,
    manifest: Value,
    inspect: InspectReport,
    selections: Vec<FrozenSelection>,
}

impl VerifiedRun {
    pub fn run(&self) -> &Value {
        &self.run
    }
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }
    pub fn inspect(&self) -> &InspectReport {
        &self.inspect
    }
    pub fn selections(&self) -> &[FrozenSelection] {
        &self.selections
    }
    pub fn public_sources(&self) -> &[Value] {
        self.run["policy_snapshots"]["source_policy"]["public_sources"].as_array().unwrap()
    }

    /// Core consumes the verified snapshots directly; callers do not restate
    /// identity, role, timestamps, Build scope or source policy during assembly.
    pub fn canonical_inputs(
        &self,
        mut outcomes: BTreeMap<usize, Vec<SourceOutcome>>,
    ) -> Result<FrozenInputs, EvidenceError> {
        require(
            outcomes.keys().all(|index| *index < self.selections.len()),
            "source outcomes refer to absent captured module",
        )?;
        let roles = array(&self.run["policy_snapshots"]["role_policy"], "modules");
        let modules = self
            .selections
            .iter()
            .zip(roles)
            .map(|(selection, role)| FrozenModule {
                selection: selection.clone(),
                role: string(role, "role").to_owned(),
                in_app: role["in_app"].as_bool().unwrap(),
                artifact_ids: self.local_artifacts(selection),
                source_outcomes: outcomes.remove(&selection.module_index).unwrap_or_default(),
            })
            .collect();
        Ok(FrozenInputs {
            workspace_id: string(&self.run["context"], "workspace_id").to_owned(),
            occurrence_id: string(&self.run, "occurrence_id").to_owned(),
            analysis_id: string(&self.run, "run_id").to_owned(),
            dump: serde_json::from_value(self.run["result_facts"]["dump"].clone())
                .map_err(|_| EvidenceError("invalid frozen result facts".to_owned()))?,
            core_image_digest: string(&self.run["context"], "core_image_digest").to_owned(),
            symbolicator_version: string(&self.run["context"], "symbolicator_version").to_owned(),
            modules,
            public_source_ids: self
                .public_sources()
                .iter()
                .map(|s| string(s, "id").to_owned())
                .collect(),
            symbol_resolution: SymbolResolution {
                selection_version: string(&self.run["context"], "selection_version").to_owned(),
                resolution_evidence_fingerprint: string(
                    &self.run,
                    "resolution_evidence_fingerprint",
                )
                .to_owned(),
                selection: serde_json::from_value(self.run["resolution_manifest"].clone()).unwrap(),
                inspect_sha256: string(&self.run["inspect"], "sha256").to_owned(),
                context_sha256: string(&self.run, "context_sha256").to_owned(),
            },
        })
    }

    fn local_artifacts(&self, _selection: &FrozenSelection) -> Vec<String> {
        Vec::new()
    }

    /// Physical staging locations are execution inputs, not semantic context.
    /// Both actual hashes must form the selected pair; filenames cannot match it.
    /// The caller owns a private immutable staging directory for the Run.
    pub fn verify_pairs(
        &self,
        pairs: &BTreeMap<String, StagedPair>,
    ) -> Result<BTreeMap<usize, PathBuf>, EvidenceError> {
        let selected = self
            .selections
            .iter()
            .filter_map(|s| s.selected_pair_id.clone())
            .collect::<BTreeSet<_>>();
        require(
            pairs.keys().cloned().collect::<BTreeSet<_>>() == selected,
            "staged pairs differ from frozen selection",
        )?;
        let mut identities = BTreeMap::new();
        for (key, pair) in pairs {
            let pe = crate::artifact::identify_artifact(&pair.pe, "pe").map_err(|_| {
                EvidenceError("selected PE identity verification failed".to_owned())
            })?;
            let pdb = crate::artifact::identify_artifact(&pair.pdb, "pdb").map_err(|_| {
                EvidenceError("selected PDB identity verification failed".to_owned())
            })?;
            require(
                !pe.is_fastlink
                    && !pdb.is_fastlink
                    && pe.debug_id.is_some()
                    && pe.debug_id == pdb.debug_id,
                "selected pair is incomplete, FASTLINK or identity-mismatched",
            )?;
            require(
                digest(&json!(["pair-v1", pe.sha256, pdb.sha256]))? == *key,
                "selected pair content digest mismatch",
            )?;
            identities.insert(
                key.clone(),
                ModuleIdentity {
                    code_id: pe.code_id.map(|s| s.to_ascii_lowercase()),
                    debug_id: pe.debug_id.map(|s| s.replace('-', "").to_ascii_lowercase()),
                    architecture: "x86_64".to_owned(),
                },
            );
        }
        let mut paths = BTreeMap::new();
        for selection in &self.selections {
            if let Some(key) = &selection.selected_pair_id {
                let actual = &identities[key];
                let captured = &selection.identity;
                require(
                    captured
                        .code_id
                        .as_ref()
                        .map_or(true, |id| Some(id) == actual.code_id.as_ref())
                        && captured
                            .debug_id
                            .as_ref()
                            .map_or(true, |id| Some(id) == actual.debug_id.as_ref())
                        && (captured.architecture == "unknown"
                            || captured.architecture == actual.architecture),
                    "selected actual pair contradicts captured module identity",
                )?;
                paths.insert(selection.module_index, pairs[key].pe.clone());
            }
        }
        Ok(paths)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StagedPair {
    pub pe: PathBuf,
    pub pdb: PathBuf,
}

pub fn verify(
    run_bytes: &[u8],
    manifest_bytes: &[u8],
    inspect_bytes: &[u8],
    dump_bytes: &[u8],
    pins: &EnginePins,
    assignment: &RunAssignment,
) -> Result<VerifiedRun, EvidenceError> {
    require(
        sha256_hex(run_bytes) == assignment.object_sha256,
        "Run object digest differs from assignment",
    )?;
    let run = strict_json(run_bytes)?;
    validate_schema(RUN_SCHEMA, &run)?;
    require(
        run["run_id"] == assignment.run_id
            && run["occurrence_id"] == assignment.occurrence_id
            && run["context"]["workspace_id"] == assignment.workspace_id,
        "Run identity differs from execution assignment",
    )?;
    require(
        sha256_hex(manifest_bytes) == string(&run["resolution_manifest"], "sha256"),
        "manifest object digest mismatch",
    )?;
    require(
        sha256_hex(inspect_bytes) == string(&run["inspect"], "sha256"),
        "inspect object digest mismatch",
    )?;
    let manifest = strict_json(manifest_bytes)?;
    validate_schema(MANIFEST_SCHEMA, &manifest)?;
    let inspected = strict_json(inspect_bytes)?;
    let native = crate::inspect_bytes(dump_bytes)
        .map_err(|_| EvidenceError("native Dump inspection failed".to_owned()))?;
    require(
        serde_json::to_value(&native)
            .map_err(|_| EvidenceError("native inspect serialization failed".to_owned()))?
            == inspected,
        "frozen inspect differs from native Dump inspection",
    )?;
    let context = &run["context"];
    require(
        digest(context)? == string(&run, "context_sha256"),
        "semantic context digest mismatch",
    )?;
    let dump_sha = sha256_hex(dump_bytes);
    require(
        run["dump"]["sha256"] == dump_sha && run["dump"]["size"] == dump_bytes.len() as u64,
        "Dump digest or size mismatch",
    )?;
    require(
        manifest["dump_sha256"] == dump_sha
            && manifest["inspect_sha256"] == run["inspect"]["sha256"],
        "manifest refers to different Dump/inspect",
    )?;
    require(
        context["core_image_digest"] == pins.core_image_digest
            && context["symbolicator_image_digest"] == pins.symbolicator_image_digest
            && context["symbolicator_version"] == pins.symbolicator_version,
        "frozen engine pins differ from executing deployment",
    )?;
    for (key, expected) in [
        ("normalization_version", NORMALIZATION_VERSION),
        ("grouping_version", GROUPING_VERSION),
        ("inspector_version", INSPECTOR_VERSION),
        ("canonical_version", "2.0"),
        ("selection_version", "pair-selection-v1"),
    ] {
        require(context[key] == expected, "unsupported frozen engine/algorithm version")?;
    }
    require(
        manifest["inspector_version"] == context["inspector_version"]
            && manifest["selection_version"] == context["selection_version"],
        "manifest engine version mismatch",
    )?;
    let facts = &run["result_facts"]["dump"];
    require(
        facts["sha256"] == run["dump"]["sha256"]
            && facts["size"] == run["dump"]["size"]
            && facts["kind"] == inspected["dump"]["kind"]
            && facts["dump_timestamp"] == inspected["dump"]["timestamp"]
            && facts["capture_profile"] == context["capture_profile"],
        "frozen result facts contradict Dump/inspect/context",
    )?;
    let time_key = match string(facts, "time_source") {
        "dump" => "dump_timestamp",
        "reported" => "reported_at",
        "uploaded" => "uploaded_at",
        "manual" => "occurred_at",
        _ => unreachable!(),
    };
    require(
        !facts[time_key].is_null() && facts["occurred_at"] == facts[time_key],
        "occurred_at contradicts time_source",
    )?;
    let policies = &run["policy_snapshots"];
    for key in ["role_policy", "source_policy"] {
        require(
            digest(&policies[key])? == context[format!("{key}_sha256")],
            "frozen policy digest mismatch",
        )?;
    }
    validate_sources(&policies["source_policy"])?;
    let selections: Vec<FrozenSelection> = serde_json::from_value(manifest["modules"].clone())
        .map_err(|_| EvidenceError("invalid frozen selections".to_owned()))?;
    let roles = array(&policies["role_policy"], "modules");
    require(
        selections.len() == native.modules.len() && roles.len() == native.modules.len(),
        "frozen modules do not cover inspect",
    )?;
    for (index, ((selection, role), captured)) in
        selections.iter().zip(roles).zip(&native.modules).enumerate()
    {
        selection.validate(index, captured, &native.process.architecture)?;
        require(
            role["module_index"] == index
                && role["identity"] == serde_json::to_value(&selection.identity).unwrap(),
            "role policy captured identity mismatch",
        )?;
        require(
            role["in_app"] == matches!(string(role, "role"), "entrypoint" | "owned"),
            "role and in_app contradict",
        )?;
    }
    require(
        resolution_fingerprint(&manifest)? == string(&run, "resolution_evidence_fingerprint"),
        "resolution fingerprint mismatch",
    )?;
    require(run_key(&run)? == string(&run, "idempotency_key"), "Run key mismatch")?;
    Ok(VerifiedRun { run, manifest, inspect: native, selections })
}

fn validate_sources(policy: &Value) -> Result<(), EvidenceError> {
    let sources = array(policy, "public_sources");
    sorted_unique(sources.iter().map(|s| &s["id"]))?;
    for source in sources {
        require(
            !string(source, "id").starts_with("crash-cap:pair:"),
            "reserved private source ID",
        )?;
        let text = string(source, "url");
        require(
            !text.chars().any(|c| c.is_whitespace() || c == '\\'),
            "invalid public source URL characters",
        )?;
        let url = reqwest::Url::parse(text)
            .map_err(|_| EvidenceError("invalid public source URL".to_owned()))?;
        require(
            matches!(url.scheme(), "http" | "https")
                && url.host_str().is_some()
                && url.port() != Some(0)
                && url.username().is_empty()
                && url.password().is_none()
                && url.query().is_none()
                && url.fragment().is_none(),
            "public source URL must be credential-free HTTP(S)",
        )?;
        for key in ["filetypes", "path_patterns"] {
            if let Some(values) = source["filters"].get(key) {
                sorted_unique(values.as_array().unwrap().iter())?;
            }
        }
    }
    Ok(())
}

pub fn resolution_fingerprint(manifest: &Value) -> Result<String, EvidenceError> {
    let mut modules = Vec::new();
    for module in manifest
        .get("modules")
        .and_then(Value::as_array)
        .ok_or_else(|| EvidenceError("manifest modules missing".to_owned()))?
    {
        let mut selected = Map::new();
        for key in [
            "module_index",
            "identity",
            "state",
            "candidates_complete",
            "candidate_pair_ids",
            "unavailable_pair_ids",
            "selected_pair_id",
            "reason",
        ] {
            selected.insert(key.to_owned(), module[key].clone());
        }
        modules.push(Value::Object(selected));
    }
    modules.sort_by_key(|m| m["module_index"].as_u64());
    digest(&json!([
        "resolution-evidence-v1",
        manifest["dump_sha256"],
        manifest["inspector_version"],
        manifest["selection_version"],
        modules
    ]))
}

pub fn run_key(run: &Value) -> Result<String, EvidenceError> {
    digest(&json!([
        "qa-run-key-v1",
        run["occurrence_id"],
        run["resolution_evidence_fingerprint"],
        run["context_sha256"],
        "2.0",
        "evidence-v1",
        run["demand_generation"],
        run["retry_attempt"]
    ]))
}

fn string<'a>(value: &'a Value, key: &str) -> &'a str {
    value[key].as_str().unwrap()
}
fn array<'a>(value: &'a Value, key: &str) -> &'a Vec<Value> {
    value[key].as_array().unwrap()
}
fn sorted_unique<'a>(values: impl Iterator<Item = &'a Value>) -> Result<(), EvidenceError> {
    let values = values.map(|v| v.as_str().unwrap()).collect::<Vec<_>>();
    require(values.windows(2).all(|w| w[0] < w[1]), "frozen list must be sorted and unique")
}

pub fn digest(value: &Value) -> Result<String, EvidenceError> {
    Ok(sha256_hex(&canonical_bytes(value)?))
}

/// qai-json-v1, independent of serde_json's optional preserve_order feature.
pub fn canonical_bytes(value: &Value) -> Result<Vec<u8>, EvidenceError> {
    fn encode(value: &Value, out: &mut Vec<u8>) -> Result<(), EvidenceError> {
        match value {
            Value::Object(map) => {
                require(map.keys().all(|k| k.is_ascii()), "qai-json-v1 requires ASCII keys")?;
                out.push(b'{');
                let mut keys = map.keys().collect::<Vec<_>>();
                keys.sort();
                for (index, key) in keys.into_iter().enumerate() {
                    if index > 0 {
                        out.push(b',');
                    }
                    out.extend(serde_json::to_vec(key).unwrap());
                    out.push(b':');
                    encode(&map[key], out)?;
                }
                out.push(b'}');
            }
            Value::Array(values) => {
                out.push(b'[');
                for (index, child) in values.iter().enumerate() {
                    if index > 0 {
                        out.push(b',');
                    }
                    encode(child, out)?;
                }
                out.push(b']');
            }
            Value::Number(number) => {
                require(
                    number.as_u64().is_some_and(|n| n <= MAX_SAFE_INTEGER)
                        || number.as_i64().is_some_and(|n| n.unsigned_abs() <= MAX_SAFE_INTEGER),
                    "qai-json-v1 requires safe integers and no floats",
                )?;
                out.extend(number.to_string().as_bytes());
            }
            _ => out.extend(serde_json::to_vec(value).unwrap()),
        }
        Ok(())
    }
    let mut bytes = Vec::new();
    encode(value, &mut bytes)?;
    Ok(bytes)
}

pub fn strict_json(bytes: &[u8]) -> Result<Value, EvidenceError> {
    require(bytes.len() <= MAX_INPUT_BYTES, "frozen JSON object exceeds input bound")?;
    let value = serde_json::from_slice::<UniqueValue>(bytes)
        .map_err(|e| EvidenceError(format!("invalid frozen JSON: {e}")))?
        .0;
    canonical_bytes(&value)?;
    Ok(value)
}

struct UniqueValue(Value);
impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct UniqueVisitor;
        impl<'de> Visitor<'de> for UniqueVisitor {
            type Value = UniqueValue;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("JSON without duplicate object keys")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Self::Value, E> {
                Ok(UniqueValue(json!(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Self::Value, E> {
                Ok(UniqueValue(json!(v)))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Self::Value, E> {
                Ok(UniqueValue(json!(v)))
            }
            fn visit_f64<E: de::Error>(self, _: f64) -> Result<Self::Value, E> {
                Err(E::custom("floating point is forbidden in frozen inputs"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Self::Value, E> {
                Ok(UniqueValue(json!(v)))
            }
            fn visit_string<E: de::Error>(self, v: String) -> Result<Self::Value, E> {
                Ok(UniqueValue(json!(v)))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueValue(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(UniqueValue(v)) = seq.next_element()? {
                    values.push(v);
                }
                Ok(UniqueValue(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut values = Map::new();
                while let Some((key, UniqueValue(value))) =
                    map.next_entry::<String, UniqueValue>()?
                {
                    if values.insert(key, value).is_some() {
                        return Err(de::Error::custom("duplicate JSON key"));
                    }
                }
                Ok(UniqueValue(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(UniqueVisitor)
    }
}

struct NoRetrieval;
impl jsonschema::Retrieve for NoRetrieval {
    fn retrieve(
        &self,
        _: &jsonschema::Uri<String>,
    ) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
        Err("external schema retrieval is forbidden".into())
    }
}
fn validate_schema(schema: &str, value: &Value) -> Result<(), EvidenceError> {
    let mut options =
        jsonschema::options().with_retriever(NoRetrieval).should_validate_formats(true);
    {
        let resource =
            include_str!("../../contracts/drafts/qa-symbol-import/analysis-context-v3.schema.json");
        let value: Value = serde_json::from_str(resource).unwrap();
        let id = value["$id"].as_str().unwrap().to_owned();
        options = options.with_resource(
            id,
            jsonschema::Resource::from_contents(value)
                .map_err(|_| EvidenceError("invalid embedded schema resource".to_owned()))?,
        );
    }
    let schema: Value = serde_json::from_str(schema).unwrap();
    let validator = options
        .build(&schema)
        .map_err(|e| EvidenceError(format!("embedded schema compilation failed: {e}")))?;
    require(validator.is_valid(value), "frozen input does not satisfy its embedded schema")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_encoding_matches_qai_unicode_integer_vector() {
        assert_eq!(
            canonical_bytes(&json!({"z":"中文","a":[null,true,-9007199254740991i64]})).unwrap(),
            "{\"a\":[null,true,-9007199254740991],\"z\":\"中文\"}".as_bytes()
        );
        assert!(canonical_bytes(&json!(1.0)).is_err());
        assert!(canonical_bytes(&json!(9007199254740992u64)).is_err());
        assert!(canonical_bytes(&json!({"中文键":1})).is_err());
    }
    #[test]
    fn duplicate_keys_and_trailing_data_are_rejected_at_any_depth() {
        for bytes in
            [br#"{"a":1,"a":2}"#.as_slice(), br#"{"a":[{"b":1,"b":2}]}"#, b"{} {}", b"{\"n\":1.0}"]
        {
            assert!(strict_json(bytes).is_err());
        }
        assert!(strict_json(br#"{"x":[null,true,-1,"text"]}"#).is_ok());
    }
}
