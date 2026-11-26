from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import Batch, BatchFolder, BatchSite
from ecom_crawler.runtime.store import (
    BatchFolderConflictError,
    BatchFolderNotFoundError,
    BatchNotFoundError,
    TaskStore,
)
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def make_batch(batch_id: str, name: str, *, folder_id: str | None = None) -> Batch:
    return Batch(batch_id=batch_id, name=name, folder_id=folder_id)


class BatchFolderStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.db")
        self.store.create_batch(make_batch("b-1", "批次一"))
        self.store.create_batch(make_batch("b-2", "批次二"))
        self.store.create_batch(make_batch("b-3", "批次三"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_nested_folders_move_batches_and_dissolve(self) -> None:
        europe = self.store.create_batch_folder(
            BatchFolder(folder_id="f-eu", name=" 欧洲 ")
        )
        uk = self.store.create_batch_folder(
            BatchFolder(folder_id="f-uk", name="英国", parent_id=europe.folder_id)
        )
        self.assertEqual(europe.name, "欧洲")
        self.assertEqual(uk.parent_id, "f-eu")

        moved = self.store.move_batches(["b-1", "b-2"], uk.folder_id)
        self.assertEqual(moved, 2)
        self.store.move_batches(["b-3"], europe.folder_id)
        self.assertEqual(self.store.get_batch("b-1").folder_id, "f-uk")

        result = self.store.delete_batch_folder("f-eu")
        self.assertEqual(result["moved_folders"], 1)
        self.assertEqual(result["moved_batches"], 1)
        self.assertIsNone(self.store.get_batch_folder("f-eu"))
        self.assertEqual(self.store.get_batch_folder("f-uk").parent_id, None)
        self.assertEqual(self.store.get_batch("b-1").folder_id, "f-uk")
        self.assertIsNone(self.store.get_batch("b-3").folder_id)

    def test_duplicate_sibling_name_and_cycle_are_rejected(self) -> None:
        parent = self.store.create_batch_folder(
            BatchFolder(folder_id="f-parent", name="Parent")
        )
        child = self.store.create_batch_folder(
            BatchFolder(folder_id="f-child", name="Child", parent_id=parent.folder_id)
        )
        with self.assertRaises(BatchFolderConflictError):
            self.store.create_batch_folder(
                BatchFolder(folder_id="f-other", name="child", parent_id="f-parent")
            )
        with self.assertRaises(BatchFolderConflictError):
            self.store.update_batch_folder(parent.folder_id, parent_id=child.folder_id)
        with self.assertRaises(BatchFolderConflictError):
            self.store.update_batch_folder(parent.folder_id, parent_id=parent.folder_id)

    def test_depth_limit_and_unknown_parent(self) -> None:
        parent_id = None
        for index in range(4):
            folder = self.store.create_batch_folder(
                BatchFolder(
                    folder_id=f"f-{index}",
                    name=f"层 {index}",
                    parent_id=parent_id,
                )
            )
            parent_id = folder.folder_id
        with self.assertRaises(BatchFolderConflictError):
            self.store.create_batch_folder(
                BatchFolder(folder_id="f-too-deep", name="第五层", parent_id=parent_id)
            )
        with self.assertRaises(BatchFolderNotFoundError):
            self.store.create_batch_folder(
                BatchFolder(folder_id="f-missing-parent", name="无父级", parent_id="nope")
            )

    def test_dissolve_rejects_sibling_name_conflict(self) -> None:
        parent = self.store.create_batch_folder(
            BatchFolder(folder_id="f-parent", name="Parent")
        )
        self.store.create_batch_folder(
            BatchFolder(folder_id="f-a", name="同名", parent_id=parent.folder_id)
        )
        self.store.create_batch_folder(BatchFolder(folder_id="f-c", name="同名"))
        with self.assertRaises(BatchFolderConflictError):
            self.store.delete_batch_folder("f-parent")

    def test_bulk_move_is_all_or_nothing(self) -> None:
        folder = self.store.create_batch_folder(
            BatchFolder(folder_id="f-target", name="Target")
        )
        with self.assertRaises(BatchNotFoundError):
            self.store.move_batches(["b-1", "missing"], folder.folder_id)
        self.assertIsNone(self.store.get_batch("b-1").folder_id)

    def test_old_batch_table_is_migrated_with_folder_id(self) -> None:
        legacy_path = self.root / "legacy.db"
        legacy = TaskStore(legacy_path)
        legacy.create_batch(make_batch("b-legacy", "旧账本批次"))
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute("DROP INDEX IF EXISTS idx_batches_folder")
            connection.execute("ALTER TABLE batches DROP COLUMN folder_id")
            connection.commit()
        finally:
            connection.close()
        reopened = TaskStore(legacy_path)
        batch = reopened.get_batch("b-legacy")
        self.assertIsNotNone(batch)
        self.assertIsNone(batch.folder_id)
        connection = sqlite3.connect(legacy_path)
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(batches)")
            }
        finally:
            connection.close()
        self.assertIn("folder_id", columns)

    def test_tree_signals_count_active_and_onboarding(self) -> None:
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="a.example",
                    domain="a.example",
                    input_value="https://a.example",
                    readiness="needs_onboarding",
                )
            ]
        )
        signals = self.store.batch_tree_signals()
        self.assertEqual(signals["b-1"]["needs_onboarding"], 1)
        self.assertEqual(signals["b-1"]["running"], 0)


class BatchFolderApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        self.store = TaskStore(self.db_path)
        self.store.create_batch(make_batch("b-1", "批次一"))
        self.store.create_batch(make_batch("b-2", "批次二"))
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_folder_crud_tree_filter_and_batch_move(self) -> None:
        created = self.client.post(
            "/api/batch-folders", json={"name": "Europe"}
        )
        self.assertEqual(created.status_code, 201, created.text)
        folder_id = created.json()["folder"]["folder_id"]

        child = self.client.post(
            "/api/batch-folders",
            json={"name": "UK", "parent_id": folder_id},
        )
        self.assertEqual(child.status_code, 201, child.text)
        child_id = child.json()["folder"]["folder_id"]

        moved = self.client.post(
            "/api/batches/move",
            json={"batch_ids": ["b-1"], "folder_id": child_id},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["moved"], 1)

        tree = self.client.get("/api/batch-tree")
        self.assertEqual(tree.status_code, 200, tree.text)
        payload = tree.json()
        self.assertEqual(len(payload["folders"]), 2)
        folders = {folder["name"]: folder for folder in payload["folders"]}
        self.assertEqual(folders["Europe"]["descendant_batch_count"], 1)
        self.assertEqual(payload["unfiled"]["batch_count"], 1)
        batches = {batch["batch_id"]: batch for batch in payload["batches"]}
        self.assertEqual(batches["b-1"]["folder_id"], child_id)

        filtered = self.client.get(
            f"/api/batches?folder_id={folder_id}&include_descendants=true"
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(filtered.json()["total"], 1)
        exact = self.client.get(
            f"/api/batches?folder_id={folder_id}&include_descendants=false"
        )
        self.assertEqual(exact.json()["total"], 0)

        renamed = self.client.patch(
            "/api/batches/b-1", json={"name": "改名批次"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["batch"]["name"], "改名批次")

        removed = self.client.delete(f"/api/batch-folders/{child_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["removed"]["moved_batches"], 1)
        self.assertEqual(self.store.get_batch("b-1").folder_id, folder_id)
        self.assertIsNotNone(self.store.get_batch_folder(folder_id))

        removed_parent = self.client.delete(f"/api/batch-folders/{folder_id}")
        self.assertEqual(removed_parent.status_code, 200, removed_parent.text)
        self.assertIsNone(self.store.get_batch("b-1").folder_id)

    def test_folder_rename_batch_create_in_folder_and_archived_filter(self) -> None:
        created = self.client.post("/api/batch-folders", json={"name": "客户 A"})
        folder_id = created.json()["folder"]["folder_id"]

        batch = self.client.post(
            "/api/batches",
            json={"name": "分组内批次", "folder_id": folder_id},
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        batch_id = batch.json()["batch"]["batch_id"]
        self.assertEqual(batch.json()["batch"]["folder_id"], folder_id)

        renamed = self.client.patch(
            f"/api/batch-folders/{folder_id}", json={"name": "客户 A（新）"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["folder"]["name"], "客户 A（新）")

        moved = self.client.patch(
            f"/api/batch-folders/{folder_id}", json={"parent_id": None}
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertIsNone(moved.json()["folder"]["parent_id"])

        archived = self.client.post(f"/api/batches/{batch_id}/archive")
        self.assertEqual(archived.status_code, 202, archived.text)
        archived_page = self.client.get("/api/batches?archived_only=true")
        self.assertEqual(archived_page.status_code, 200, archived_page.text)
        self.assertEqual(
            [item["batch_id"] for item in archived_page.json()["items"]], [batch_id]
        )

    def test_conflicts_unknown_folder_and_read_only(self) -> None:
        first = self.client.post("/api/batch-folders", json={"name": "Same"})
        self.assertEqual(first.status_code, 201)
        duplicate = self.client.post("/api/batch-folders", json={"name": "same"})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        missing = self.client.post(
            "/api/batches/move", json={"batch_ids": ["b-1"], "folder_id": "missing"}
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        read_only = TestClient(
            create_app(
                self.db_path,
                self.out_root,
                self.rules_dir,
                read_only=True,
            ),
            headers=CLIENT_HEADERS,
        )
        self.assertEqual(read_only.get("/api/batch-tree").status_code, 200)
        blocked = read_only.post("/api/batch-folders", json={"name": "Blocked"})
        self.assertEqual(blocked.status_code, 403, blocked.text)


if __name__ == "__main__":
    unittest.main()
