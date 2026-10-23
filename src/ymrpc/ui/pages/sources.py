"""Страница «Источники»: режим захвата, сессия и правила приложений."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...i18n import t
from ...models import AppRule, CaptureMode, PlaybackStatus, PlaybackView, RuleAction, Settings
from .. import icons, theme
from ..widgets import (
    Card,
    ElidedLabel,
    IconButton,
    OptionCard,
    Page,
    SoftCard,
)


class SourcesPage(Page):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("sources.title"), t("sources.subtitle"), parent)
        self._rules: list[AppRule] = []
        self._sessions = []
        self._view = PlaybackView()
        self._selected_session = ""
        self._current_mode = CaptureMode.AUTO
        self._mode_cards: dict[CaptureMode, OptionCard] = {}

        self._build_mode()
        self._build_session()
        self._build_rules()

    # ------------------------------------------------------------------ build

    def _build_mode(self) -> None:
        card = Card(padding=18)
        title = QLabel(t("sources.capture"), card)
        title.setObjectName("h2")
        card.add(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (mode, name, hint) in enumerate(
            (
                (CaptureMode.AUTO, t("sources.capture_auto"), t("sources.capture_auto_hint")),
                (CaptureMode.WINDOWS, t("sources.capture_windows"), t("sources.capture_windows_hint")),
                (CaptureMode.YNISON, t("sources.capture_ynison"), t("sources.capture_ynison_hint")),
            )
        ):
            option = OptionCard(name, hint, card)
            group.addButton(option, index)
            self._mode_cards[mode] = option
            row.addWidget(option, 1)
        group.idToggled.connect(lambda _index, checked: checked and self.notify())
        card.add_layout(row)
        self.add(card)

    def _build_session(self) -> None:
        card = Card(padding=18)
        title = QLabel(t("sources.session"), card)
        title.setObjectName("h2")
        card.add(title)
        hint = QLabel(t("sources.session_hint"), card)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)
        self.session_combo = QComboBox(card)
        self.session_combo.setMinimumWidth(320)
        self.session_combo.currentIndexChanged.connect(self._session_changed)
        card.add(self.session_combo)
        self.session_note = QLabel("", card)
        self.session_note.setObjectName("tiny")
        self.session_note.setTextFormat(Qt.TextFormat.PlainText)
        self.session_note.setWordWrap(True)
        card.add(self.session_note)
        self.add(card)

    def _build_rules(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("sources.rules"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        self.add_current_button = QPushButton(t("sources.rule_current"), card)
        self.add_current_button.setIcon(icons.icon("plus", theme.MUTED, 15))
        self.add_current_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_current_button.setEnabled(False)
        self.add_current_button.clicked.connect(self._add_current_source)
        header.addWidget(self.add_current_button)
        card.add_layout(header)

        hint = QLabel(t("sources.rules_hint"), card)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)

        self.rules_box = QVBoxLayout()
        self.rules_box.setSpacing(8)
        card.add_layout(self.rules_box)
        self.empty_rules = QLabel(t("sources.rule_empty"), card)
        self.empty_rules.setObjectName("tiny")
        self.empty_rules.setWordWrap(True)
        card.add(self.empty_rules)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.rule_input = QLineEdit(card)
        self.rule_input.setPlaceholderText("chrome / Spotify.exe / AIMP")
        self.rule_input.returnPressed.connect(self._add_rule)
        add_row.addWidget(self.rule_input, 1)
        self.rule_action = QComboBox(card)
        self.rule_action.addItem(t("sources.rule_ignore"), RuleAction.IGNORE.value)
        self.rule_action.addItem(t("sources.rule_prefer"), RuleAction.PREFER.value)
        add_row.addWidget(self.rule_action)
        self.rule_add = QPushButton(t("sources.rule_add"), card)
        self.rule_add.setObjectName("primary")
        self.rule_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rule_add.clicked.connect(self._add_rule)
        add_row.addWidget(self.rule_add)
        card.add_layout(add_row)
        self.add(card)

    # ------------------------------------------------------------------ load

    def _load(self, settings: Settings) -> None:
        self._current_mode = settings.capture_mode
        card = self._mode_cards.get(settings.capture_mode)
        if card is None:
            card = self._mode_cards[CaptureMode.AUTO]
            self._current_mode = CaptureMode.AUTO
        card.setChecked(True)
        self._rules = list(settings.rules)
        self._selected_session = settings.selected_session
        self._render_rules()
        self._render_sessions()

    def _session_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self._selected_session = self.session_combo.itemData(index) or ""
        self.session_note.setText(self._selected_session)
        self.notify()

    def _render_sessions(self) -> None:
        current = self._selected_session
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem(t("sources.session_auto"), "")
        found = False
        for info in self._sessions:
            label = info.source_name
            if info.status == PlaybackStatus.PLAYING:
                label = "▶  " + label
            elif info.status == PlaybackStatus.PAUSED:
                label = "❚❚  " + label
            self.session_combo.addItem(label, info.source_id)
            self.session_combo.setItemData(
                self.session_combo.count() - 1, info.source_id, Qt.ItemDataRole.ToolTipRole
            )
            if info.source_id == current:
                self.session_combo.setCurrentIndex(self.session_combo.count() - 1)
                found = True
        if current and not found:
            self.session_combo.addItem(f"{current} ({t('app.unknown')})", current)
            self.session_combo.setCurrentIndex(self.session_combo.count() - 1)
        self.session_combo.blockSignals(False)
        self.session_note.setText(current)

    def set_sessions(self, sessions) -> None:
        self._sessions = list(sessions)
        if not self._loading:
            self._render_sessions()

    def _render_rules(self) -> None:
        while self.rules_box.count():
            item = self.rules_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for rule in self._rules:
            self.rules_box.addWidget(self._rule_row(rule))
        self.empty_rules.setVisible(not self._rules)

    def _rule_row(self, rule: AppRule) -> QWidget:
        frame = SoftCard(self, padding=10)
        layout = QHBoxLayout()
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(0)
        pattern = ElidedLabel(rule.pattern, frame)
        pattern.setStyleSheet("font-weight: 600;")
        pattern.setToolTip(rule.pattern)
        meta = QLabel(
            t("sources.rule_prefer") if rule.action == RuleAction.PREFER else t("sources.rule_ignore"),
            frame,
        )
        meta.setObjectName("tiny")
        text.addWidget(pattern)
        text.addWidget(meta)
        layout.addLayout(text, 1)

        action = QComboBox(frame)
        action.addItem(t("sources.rule_ignore"), RuleAction.IGNORE.value)
        action.addItem(t("sources.rule_prefer"), RuleAction.PREFER.value)
        action.setCurrentIndex(1 if rule.action == RuleAction.PREFER else 0)
        action.setFixedWidth(130)
        layout.addWidget(action)

        priority = QSpinBox(frame)
        priority.setRange(-100, 100)
        priority.setValue(rule.priority)
        priority.setFixedWidth(72)
        priority.setEnabled(rule.action == RuleAction.PREFER)
        layout.addWidget(priority)

        remove = IconButton("trash", t("app.delete"), frame, size=30, icon_size=16)
        layout.addWidget(remove)
        frame.body.addLayout(layout)

        def update_action(index: int) -> None:
            value = RuleAction(action.itemData(index))
            priority.setEnabled(value == RuleAction.PREFER)
            meta.setText(
                t("sources.rule_prefer") if value == RuleAction.PREFER else t("sources.rule_ignore")
            )
            self._replace_rule(rule.pattern, action=value)

        action.currentIndexChanged.connect(update_action)
        priority.valueChanged.connect(
            lambda value: self._replace_rule(rule.pattern, priority=value)
        )
        remove.clicked.connect(lambda: self._remove_rule(rule.pattern))
        return frame

    def _replace_rule(
        self,
        pattern: str,
        *,
        action: RuleAction | None = None,
        priority: int | None = None,
    ) -> None:
        updated = []
        for item in self._rules:
            if item.pattern == pattern:
                item = AppRule(
                    pattern=item.pattern,
                    action=action if action is not None else item.action,
                    priority=priority if priority is not None else item.priority,
                )
            updated.append(item)
        self._rules = updated
        self.notify()

    def _remove_rule(self, pattern: str) -> None:
        self._rules = [item for item in self._rules if item.pattern != pattern]
        self._render_rules()
        self.notify()

    def _add_rule(self) -> None:
        pattern = self.rule_input.text().strip()
        if not pattern:
            self.rule_input.setFocus()
            return
        action = RuleAction(self.rule_action.currentData())
        self._rules = [item for item in self._rules if item.pattern.casefold() != pattern.casefold()]
        self._rules.append(AppRule(pattern=pattern[:120], action=action))
        self.rule_input.clear()
        self._render_rules()
        self.notify()

    def _add_current_source(self) -> None:
        source = self._view.source_id
        if not source:
            return
        if any(item.pattern.casefold() == source.casefold() for item in self._rules):
            return
        self._rules.append(AppRule(pattern=source[:120], action=RuleAction.IGNORE, priority=100))
        self._render_rules()
        self.notify()

    # ------------------------------------------------------------------ state

    def update_view(self, view: PlaybackView) -> None:
        self._view = view
        self.add_current_button.setEnabled(bool(view.source_id))

    def apply_to(self, settings: Settings) -> Settings:
        mode = self._current_mode
        for candidate, card in self._mode_cards.items():
            if card.isChecked():
                mode = candidate
                break
        return replace(
            settings,
            capture_mode=mode,
            selected_session=self.session_combo.currentData() or "",
            rules=tuple(self._rules),
        )
