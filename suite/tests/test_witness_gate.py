"""The publication boundary: which evidence the console is allowed to make a claim from.

Every test here drives the real gate against a real artifact copied to a temp tree, then breaks
exactly one thing. A gate is only worth having if each refusal can be produced on demand, and the
suite's job is to produce them.
"""
import hashlib
import json
import pathlib
import shutil

import pytest

import witness_gate as G

SUITE = pathlib.Path(__file__).resolve().parent.parent
REAL_MANIFEST = SUITE / "witness.manifest.json"


@pytest.fixture
def bed(tmp_path):
    """A private home + manifest the test can corrupt without touching the repo."""
    m = json.loads(REAL_MANIFEST.read_text())
    src = pathlib.Path.home() / m["artifact"]
    dst = tmp_path / m["artifact"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    mp = tmp_path / "witness.manifest.json"
    mp.write_text(json.dumps(m, indent=1))

    def write_artifact(obj):
        dst.write_text(json.dumps(obj, indent=1) + "\n")
        mm = json.loads(mp.read_text())
        mm["sha256"] = hashlib.sha256(dst.read_bytes()).hexdigest()
        mp.write_text(json.dumps(mm, indent=1))

    pristine = dst.read_bytes()
    pristine_manifest = mp.read_text()

    def reset():
        """Loop-style tests mutate the file in place, so each iteration must start from the
        original bytes. Without this, iteration 2 deletes a second field from an artifact that
        is already missing the first, and the assertion matches the wrong refusal."""
        dst.write_bytes(pristine)
        mp.write_text(pristine_manifest)

    return {"home": tmp_path, "manifest": mp, "artifact": dst, "reset": reset,
            "load": lambda: json.loads(dst.read_text()),
            "write": write_artifact,
            "set_manifest": lambda o: mp.write_text(json.dumps(o, indent=1)),
            "get_manifest": lambda: json.loads(mp.read_text())}


def _accept(bed):
    return G.accept(manifest_path=bed["manifest"], home=bed["home"])


def test_1_happy_path_accepts_and_derives_the_expected_totals(bed):
    a = _accept(bed)
    h = G.headline(a)
    assert (h["caught"], h["missed"], h["applied"]) == (42, 4, 46)
    assert h["not_applicable"] == 223 and h["incomplete"] == 0 and h["rows"] == 269
    assert h["scored"] is True


def test_2_one_changed_byte_without_a_manifest_update_is_refused(bed):
    raw = bed["artifact"].read_bytes()
    bed["artifact"].write_bytes(raw.replace(b'"caught": 42', b'"caught": 43', 1))
    with pytest.raises(G.WitnessRejected, match="sha256"):
        _accept(bed)


def test_4_a_dirty_stamp_is_refused(bed):
    a = bed["load"](); a["witness_protocol"]["stamp"]["dirty"] = True; bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="stamp.dirty"):
        _accept(bed)


def test_5_a_missing_stamp_is_refused(bed):
    a = bed["load"](); del a["witness_protocol"]["stamp"]; bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="stamp"):
        _accept(bed)


def test_5b_each_required_stamp_field_is_required(bed):
    for field in ("issuer_commit", "code_paths", "dirty", "rule"):
        bed["reset"]()
        a = bed["load"](); del a["witness_protocol"]["stamp"][field]; bed["write"](a)
        with pytest.raises(G.WitnessRejected, match=f"stamp.{field}"):
            _accept(bed)


def test_6_a_protocol_mismatch_is_refused(bed):
    a = bed["load"](); a["witness_protocol"]["protocol"] = "evalmut-invocation-witness-v2"
    bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="protocol"):
        _accept(bed)


def test_7_a_library_provenance_mismatch_is_refused(bed):
    """The gate holds manifest intent against artifact fact. It never hard-codes a version."""
    a = bed["load"](); a["witness_protocol"]["libraries"] = [{"name": "gradecore",
                                                             "version": "0.10.1"}]
    bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="library"):
        _accept(bed)
    assert "0.10.2" not in pathlib.Path(G.__file__).read_text(), (
        "the gate hard-codes a library version; that is the drift gradecore 0.10.2 fixed")


def test_8_a_headline_not_recomputable_from_raw_returns_is_refused(bed):
    """Edit the tally alone. The evidence underneath still says 42, so the page must refuse."""
    a = bed["load"](); a["tally"]["caught"] = 46; bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="tally.caught recomputed"):
        _accept(bed)


def test_8b_an_edited_row_outcome_is_refused(bed):
    a = bed["load"]()
    for r in a["results"]:
        if r.get("witness_status") == "WITNESSED" and r["outcome"] == "caught":
            r["outcome"] = "missed"
            break
    bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="outcome for"):
        _accept(bed)


def test_incomplete_rows_block_publication(bed):
    a = bed["load"](); a["witness_protocol"]["row_counts"]["incomplete"] = 1; bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="row_counts.incomplete"):
        _accept(bed)


def test_unattributed_calls_block_publication(bed):
    a = bed["load"]()
    a["results"][0].setdefault("witness", {})["unattributed_calls"] = 1
    bed["write"](a)
    with pytest.raises(G.WitnessRejected, match="unattributed"):
        _accept(bed)


def test_a_missing_artifact_is_refused_not_defaulted(bed):
    bed["artifact"].unlink()
    with pytest.raises(G.WitnessRejected, match="artifact"):
        _accept(bed)


def test_the_public_url_must_agree_with_the_fields_beside_it(bed):
    """A manifest can be internally plausible and mutually inconsistent. The url is the only
    field a reader can act on, so a url naming a different commit sends them to evidence this
    build never saw."""
    for bad, pat in (
        ("https://github.com/egnaro9/evalmut/blob/deadbee/docs/dogfood_gradecore_witnessed.json",
         "public_url commit"),
        ("https://github.com/egnaro9/gradecore/blob/8cb21bd/docs/dogfood_gradecore_witnessed.json",
         "public_url repo"),
        ("https://github.com/egnaro9/evalmut/blob/8cb21bd/docs/other.json", "public_url path"),
        ("https://example.com/whatever", "public_url"),
    ):
        m = bed["get_manifest"](); m["public_url"] = bad; bed["set_manifest"](m)
        with pytest.raises(G.WitnessRejected, match=pat):
            _accept(bed)


def test_the_gate_has_no_fallback_branch():
    """A gate with a quiet path is the defect this project keeps finding. accept() either
    returns an accepted artifact or raises; there is no third outcome to accidentally take."""
    src = pathlib.Path(G.__file__).read_text()
    body = src[src.index("def accept("):src.index("def _reconcile(")]
    assert "except WitnessRejected" not in src, "the gate catches its own refusal somewhere"
    assert body.count("return ") == 1, (
        "accept() has more than one return; a second one is a fallback path")
