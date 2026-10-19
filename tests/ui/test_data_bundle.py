"""Tar import uses checked paths/bytes and never replaces existing data or private settings."""

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest

from scripts import data_bundle as bundle
from scripts.package_data import scan_secrets

SAFE_FILE = "data/derived/j2-full/answers.jsonl"
SECOND = f"runs/{bundle.RUN_NAMES[0]}/_COMPLETE.json"


def make_archive(tmp_path, entries=None, *, overrides=None):
    entries = entries or [(SAFE_FILE, b"synthetic data"), (SECOND, b"synthetic run")]
    archive = tmp_path / bundle.BUNDLE_NAME
    files = {}
    with tarfile.open(archive, "w:gz") as target:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            if overrides:
                for key, value in overrides.items():
                    setattr(info, key, value)
            target.addfile(info, io.BytesIO(content))
            files[name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    manifest = {"format": "stapfer-bootstrap-v1", "archive_sha256": bundle.digest(archive), "files": files}
    (tmp_path / bundle.MANIFEST_NAME).write_text(json.dumps(manifest))
    return archive


def test_fresh_install_and_repeat_preserve_private_files(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    root = tmp_path / "install"
    root.mkdir()
    (root / ".env.review-oauth").write_text("keep private")
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {"software_test": True})
    first = bundle.install_bundle(root, archive)
    assert first["installed"] == 2
    second = bundle.install_bundle(root, archive)
    assert second["installed"] == 0 and second["reused"] == 2
    assert (root / ".env.review-oauth").read_text() == "keep private"
    assert (root / SAFE_FILE).read_bytes() == b"synthetic data"


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "runs/../outside", "runs\\x",
    "data/derived/j2-full/.env", "runs/reviewer-exports/person/reviews.jsonl", "data/raw/dump.sql",
    f"runs/{bundle.RUN_NAMES[0]}/aux.json", f"runs/{bundle.RUN_NAMES[0]}/file.json:",
    f"runs/{bundle.RUN_NAMES[0]}/trailing./x.json", "data//derived/j2-full/answers.jsonl",
    f"runs/{bundle.RUN_NAMES[0]}/bad?.json", f"runs/{bundle.RUN_NAMES[0]}/bad\n.json"])
def test_unsafe_manifest_names_are_rejected(tmp_path, name):
    make_archive(tmp_path, [(name, b"unsafe")])
    with pytest.raises(bundle.BundleError):
        bundle.read_manifest(tmp_path / bundle.MANIFEST_NAME)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.DIRTYPE])
def test_links_devices_and_directory_entries_cannot_be_extracted(tmp_path, monkeypatch, kind):
    archive = make_archive(tmp_path, [(SAFE_FILE, b"")], overrides={"type": kind, "linkname": "/outside"})
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError):
        bundle.install_bundle(tmp_path / "install", archive)


def test_existing_conflict_blocks_every_new_file(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    root = tmp_path / "install"
    (root / SAFE_FILE).parent.mkdir(parents=True)
    (root / SAFE_FILE).write_text("user's existing data")
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="nothing was overwritten"):
        bundle.install_bundle(root, archive)
    assert not (root / SECOND).exists()
    assert (root / SAFE_FILE).read_text() == "user's existing data"


def test_corrupted_archive_is_rejected_before_unpacking(tmp_path):
    archive = make_archive(tmp_path)
    with archive.open("ab") as target:
        target.write(b"tamper")
    with pytest.raises(bundle.BundleError, match="checksum"):
        bundle.install_bundle(tmp_path / "install", archive)
    assert not (tmp_path / "install").exists()


def test_duplicate_tar_members_are_rejected(tmp_path, monkeypatch):
    archive = make_archive(tmp_path, [(SAFE_FILE, b"one"), (SAFE_FILE, b"one")])
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="duplicate"):
        bundle.install_bundle(tmp_path / "install", archive)


def test_wrong_member_hash_is_rejected_before_installation(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    path = tmp_path / bundle.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    manifest["files"][SAFE_FILE]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="checksum"):
        bundle.install_bundle(tmp_path / "install", archive)
    assert not (tmp_path / "install" / SAFE_FILE).exists()


def test_missing_member_and_oversized_manifest_are_rejected(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    path = tmp_path / bundle.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    manifest["files"][f"runs/{bundle.RUN_NAMES[1]}/missing.json"] = {"size": 1, "sha256": "0" * 64}
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="missing"):
        bundle.install_bundle(tmp_path / "install", archive)
    manifest["files"][SAFE_FILE]["size"] = bundle.MAX_BYTES + 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(bundle.BundleError, match="size"):
        bundle.read_manifest(path)


@pytest.mark.parametrize("content", [b'{"api_key":"synthetic-private-value"}', b'{"headers":{"Authorization":"Bearer fake"}}',
                                   b'"hf_' + b'Q'*30 + b'"'])
def test_packager_rejects_credentials_without_echoing_them(tmp_path, content):
    path = tmp_path / "record.json"
    path.write_bytes(content)
    with pytest.raises(bundle.BundleError) as result:
        scan_secrets(path)
    assert "synthetic-private-value" not in str(result.value) and "Bearer fake" not in str(result.value)


def test_human_authorization_audit_note_is_not_an_http_credential(tmp_path):
    path = tmp_path / "amendment-provenance.json"
    path.write_text(json.dumps({"authorization": "The user explicitly authorized this review amendment for the historical audit."}))
    scan_secrets(path)
    path.write_text(json.dumps({"authorization": "Jean replied then do it after the review amendment explanation was provided."}))
    scan_secrets(path)
    path.write_text(json.dumps({"authorization": "Bearer user authorized secret text that must be blocked"}))
    with pytest.raises(bundle.BundleError):
        scan_secrets(path)


def test_existing_symlink_parent_is_never_followed(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    root, outside = tmp_path / "install", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "data").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This platform does not allow test symlinks")
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="symlink"):
        bundle.install_bundle(root, archive)
    assert not list(outside.iterdir())


def test_existing_non_directory_parent_is_preserved_before_any_install(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    root = tmp_path / "install"
    root.mkdir()
    (root / "data").write_text("preserve this user's file")
    monkeypatch.setattr(bundle, "verify_contents", lambda path: {})
    with pytest.raises(bundle.BundleError, match="parent"):
        bundle.install_bundle(root, archive)
    assert (root / "data").read_text() == "preserve this user's file"
    assert not (root / "runs").exists()


def test_case_collisions_and_other_powershell_scripts_are_rejected(tmp_path):
    archive = make_archive(tmp_path, [(SECOND, b"first"), (SECOND.replace("_COMPLETE", "_complete"), b"second")])
    with pytest.raises(bundle.BundleError):
        bundle.read_manifest(tmp_path / bundle.MANIFEST_NAME)
    assert bundle.allowed_name(f"runs/{bundle.RUN_NAMES[0]}/references/Read-PublicReferenceSource.ps1")
    assert not bundle.allowed_name(f"runs/{bundle.RUN_NAMES[0]}/references/other.ps1")


def test_insufficient_disk_blocks_unpacking_before_data_is_written(tmp_path, monkeypatch):
    archive = make_archive(tmp_path)
    monkeypatch.setattr(bundle.shutil, "disk_usage", lambda root: SimpleNamespace(free=0))
    with pytest.raises(bundle.BundleError, match="disk"):
        bundle.install_bundle(tmp_path / "install", archive)
    assert not (tmp_path / "install" / SAFE_FILE).exists()
