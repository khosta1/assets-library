"""What a fresh copy of the app shows before it shows an empty grid.

A new install has nothing: an empty `library/`, no servers, and a window that
looks broken rather than new. Somebody who did not build this cannot tell "no
assets yet" from "it did not work", and nothing on screen mentions that a
server exists at all.

So the first launch asks the two questions that matter and gets out of the way:

    where does this copy keep its own assets    (it already knows; it says so)
    is there a server, and what is its token    (the only thing it cannot guess)

One panel, not a wizard. A wizard implies steps that depend on each other and
these do not - and a beginner who takes a wrong turn in a wizard has to start
over, while a panel just sits there with a field still empty.

**Skippable, and it never nags.** Once dismissed it does not come back, because
an app that re-asks a question you declined is an app you learn to click past
without reading. Library ▸ Remote libraries… is where it lives afterwards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from assetlib import remote, shortcut

SETUP_DONE = "setup_seen"


def needs_setup(cfg, asset_count: int, hosts: list) -> bool:
    """True when this copy has nothing and has never been asked.

    All three conditions, deliberately. An empty library alone is not enough -
    someone can legitimately empty theirs - and a missing server alone is not
    either, because a local-only library is a perfectly good way to use this.
    It is the combination, on a copy that has never seen this panel, that means
    "fresh install" rather than "deliberate state".
    """
    # A host with no token is an ADDRESS, not a connection - it is what
    # "Create a new library…" leaves behind so the person receiving the copy is
    # asked for one thing instead of three. Treating it as configured would
    # hide the panel and leave them with a server they cannot reach and no
    # visible way to fix it.
    usable = [h for h in hosts if h.token]
    if usable or asset_count:
        return False
    return not (cfg.remote_dir() / SETUP_DONE).exists()


def mark_seen(cfg) -> None:
    """Remember that the question was asked. A marker file, not a config key.

    config/ is committed and shared; this is a fact about one copy on one disk,
    and it belongs with the other per-copy state in .assetlib/.
    """
    try:
        path = cfg.remote_dir() / SETUP_DONE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("This copy has shown the setup panel once.\n",
                        encoding="utf-8")
    except OSError:
        pass                    # a marker that cannot be written is not fatal


class FirstRunDialog(QDialog):
    def __init__(self, cfg, parent=None, suggested=None):
        super().__init__(parent)
        self.cfg = cfg
        self.hosts: list = []
        self.sync_requested = False
        self.shortcut_requested = False
        self.setWindowTitle("Set up your asset library")
        self.setMinimumWidth(620)

        title = QLabel("Welcome to Asset Library")
        font = QFont(title.font())
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        title.setFont(font)

        intro = QLabel(
            "This copy is empty. That is normal for a new install.\n\n"
            "Assets live in one of two places: in this folder, or on a server "
            "you connect to. You can use either, or both.")
        intro.setWordWrap(True)

        # Said out loud rather than left to be discovered. "Where did my assets
        # go" is the first question anyone asks, and the answer is a path.
        where = QLabel(f"<b>This copy stores its assets in</b><br>{cfg.library}")
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextSelectableByMouse)

        rule = QFrame()
        rule.setFrameShape(QFrame.HLine)

        server = QLabel("<b>Connect to a server</b>  (optional)")
        explain = QLabel(
            "If someone gave you an address and a token, put them here. You "
            "will be able to browse everything the server holds without "
            "downloading any of it — assets come down only when you ask for "
            "one.")
        explain.setWordWrap(True)

        # Prefilled when the copy was made by "Create a new library…", which
        # leaves behind every way of REACHING the server and never the token.
        # Then the only empty field on screen is the one only a person can
        # supply.
        self.suggested = suggested
        self.name = QLineEdit(suggested.name if suggested else "rocky")
        self.url = QLineEdit(suggested.url if suggested else "")
        self.url.setPlaceholderText("http://10.209.73.177:8083")
        self.token = QLineEdit()
        self.token.setPlaceholderText("the token you were given")
        # Not echoed. Someone is going to do this with a person looking over
        # their shoulder, and a token is a password even when it is called a
        # token. Revealable, because a typo in a masked field is unfindable.
        self.token.setEchoMode(QLineEdit.Password)

        reveal = QCheckBox("Show")
        reveal.toggled.connect(
            lambda on: self.token.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))

        token_row = QHBoxLayout()
        token_row.addWidget(self.token, 1)
        token_row.addWidget(reveal)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Address", self.url)
        form.addRow("Token", token_row)

        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._test)
        self.result = QLabel("")
        self.result.setWordWrap(True)

        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.result, 1)

        self.sync_box = QCheckBox("Download the catalogue now (a few kilobytes)")
        self.sync_box.setChecked(True)

        self.shortcut_box = QCheckBox("Put a shortcut on my Desktop")
        # Offered, never assumed. Writing to someone's Desktop uninvited is the
        # behaviour people install cleanup tools to undo - and it is switched
        # off if one is already sitting there.
        self.shortcut_box.setChecked(shortcut.available()
                                     and not shortcut.already_there())
        self.shortcut_box.setVisible(shortcut.available())

        buttons = QDialogButtonBox()
        buttons.addButton("Finish", QDialogButtonBox.AcceptRole)
        buttons.addButton("Skip for now", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._finish)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(where)
        layout.addWidget(rule)
        layout.addWidget(server)
        layout.addWidget(explain)
        layout.addLayout(form)
        layout.addLayout(test_row)
        layout.addWidget(self.sync_box)
        layout.addWidget(self.shortcut_box)
        layout.addStretch(1)
        layout.addWidget(buttons)

    # --------------------------------------------------------------- actions

    def _host(self):
        """The server as declared here, plus what the copy already knew.

        The share and the SSH account are carried through rather than shown.
        This panel asks for the one thing it cannot know, and two more fields
        that are already correct would make it look like a form rather than a
        question. They are editable afterwards in Library > Remote libraries.
        """
        name = self.name.text().strip()
        url = self.url.text().strip()
        if not name or not url:
            return None
        prior = self.suggested
        return remote.Host(name=name, url=url, token=self.token.text().strip(),
                           share=prior.share if prior else "",
                           ssh=prior.ssh if prior else "")

    def _test(self) -> None:
        from .remote_libraries import health_async

        host = self._host()
        if host is None:
            self.result.setText("Fill in a name and an address first.")
            return
        self.test_btn.setEnabled(False)
        self.result.setText("asking…")
        health_async([host], self._tested)

    def _tested(self, results: list) -> None:
        self.test_btn.setEnabled(True)
        if not results:
            return
        _name, ok, message = results[0]
        self.result.setText(("✓  " if ok else "✗  ") + message)

    def _finish(self) -> None:
        host = self._host()
        if host is not None:
            self.hosts = [host]
            remote.save_hosts(self.cfg, self.hosts)
            self.sync_requested = self.sync_box.isChecked()
        self.shortcut_requested = (self.shortcut_box.isVisible()
                                   and self.shortcut_box.isChecked())
        self.accept()
