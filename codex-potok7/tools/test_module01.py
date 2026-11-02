#!/usr/bin/env python3
"""Behavioral tests of the installer, not a live client/onboarding test."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'module-01-architecture/skill/ikigai-brain-architect'
spec = importlib.util.spec_from_file_location('setup_brain', SKILL / 'scripts/setup_brain.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
FILES = setup.package_files(SKILL)


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class ModuleOne(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='potok7-module01-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_does_not_mutate(self):
        result = setup.apply_files(self.root, FILES)
        self.assertGreater(len(result['would_create']), 10)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_clean_install_and_personal_edits_survive_repeat(self):
        setup.apply_files(self.root, FILES, True)
        task = self.root / 'memory/tasks/task_2026-11-02_demo.md'
        task.write_text('Учебная задача: подготовить встречу\nРезультат: 3 вопроса\nФраза: тихий маяк\n', encoding='utf-8')
        focus = self.root / 'memory/ACTIVE.md'
        focus.write_text('Мой личный фокус\n', encoding='utf-8')
        before = snapshot(self.root)
        result = setup.apply_files(self.root, FILES, True)
        self.assertEqual(result['created'], [])
        self.assertEqual(before, snapshot(self.root))
        self.assertEqual(result['session_test'], 'not_run')

    def test_existing_brain_is_not_touched(self):
        for name in ('AGENTS.md', 'CLAUDE.md', 'memory'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root/name).mkdir() if name == 'memory' else (root/name).write_text('Личное', encoding='utf-8')
                before = snapshot(root)
                with self.assertRaises(ValueError):
                    setup.apply_files(root, FILES, True)
                self.assertEqual(before, snapshot(root))
                self.assertFalse((root/'.ikigai').exists())

    def test_restore_missing_file_without_replacing_changed_file(self):
        setup.apply_files(self.root, FILES, True)
        (self.root/'SYSTEM.md').unlink()
        (self.root/'AGENTS.md').write_text('Мои изменённые правила', encoding='utf-8')
        result = setup.apply_files(self.root, FILES, True)
        self.assertEqual(result['created'], ['SYSTEM.md'])
        self.assertEqual((self.root/'AGENTS.md').read_text(), 'Мои изменённые правила')

    def test_symlink_and_escape_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as external:
            (self.root/'.agents').symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                setup.apply_files(self.root, FILES, True)
            self.assertEqual(list(Path(external).iterdir()), [])
            self.assertFalse((self.root/'.ikigai').exists())
        for name in ('../escape', '/absolute', 'a/../../escape', 'a\\escape'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                setup.safe_path(self.root, name)

    def test_path_collision_rejected_before_write(self):
        (self.root/'.agents').write_text('keep', encoding='utf-8')
        before = snapshot(self.root)
        with self.assertRaises(ValueError):
            setup.apply_files(self.root, FILES, True)
        self.assertEqual(before, snapshot(self.root))

    def test_new_session_status_not_faked(self):
        setup.apply_files(self.root, FILES, True)
        info = json.loads((self.root/setup.MARKER).read_text())
        self.assertEqual(info['session_test'], 'not_run')

    def test_autonomous_start_is_same_payload(self):
        text = (ROOT/'module-01-architecture/START.md').read_text(encoding='utf-8')
        code = text.split('```python\n', 1)[1].split('\n```', 1)[0]
        namespace = {'__name__': 'check_embedded'}
        exec(compile(code, 'START.md', 'exec'), namespace)
        self.assertEqual(namespace['FILES'], FILES)
        namespace['apply_files'](self.root, namespace['FILES'], True)
        self.assertTrue((self.root/'.agents/skills/ikigai-brain-architect/SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
