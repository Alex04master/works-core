# -*- coding: utf-8 -*-
"""Хранилище: реестр JSON с атомарной записью."""
import json
import os
import threading


class Store:
    """Реестр курсов, занятий, заданий, студентов и сдач."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.reg = os.path.join(self.root, "реестр.json")
        self.mat = os.path.join(self.root, "раздатка")
        self.subs = os.path.join(self.root, "сдачи")
        self.mod_data = os.path.join(self.root, "модули")
        for d in (self.root, self.mat, self.subs, self.mod_data):
            os.makedirs(d, exist_ok=True)
        self.lock = threading.Lock()
        self.db = self._load()

    def _blank(self):
        return {"версия": 3, "курсы": [], "занятия": [], "задания": [],
                "студенты": [], "сдачи": {}}

    def _load(self):
        try:
            with open(self.reg, encoding="utf-8") as f:
                db = json.load(f)
        except (OSError, ValueError):
            return self._blank()
        bk = self._blank()
        for k, v in bk.items():
            db.setdefault(k, v)
        return db

    def save(self):
        """Атомарная запись: .tmp → os.replace."""
        tmp = self.reg + ".tmp"
        with self.lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.reg)

    def __getitem__(self, key):
        return self.db[key]

    def __setitem__(self, key, val):
        self.db[key] = val