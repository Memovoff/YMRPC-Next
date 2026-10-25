"""Страница «Discord»: тип статуса, шаблоны и живой предпросмотр."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import t
from ...models import ActivityKind, ButtonsMode, Settings
from ...presence import DEFAULT_DETAILS, DEFAULT_LARGE_TEXT, DEFAULT_STATE, preview, validate_template
from .. import theme
from ..widgets import Card, CoverWidget, ElidedLabel, Field, Page, ToggleRow


class DiscordPreview(QFrame):
    """Макет карточки Discord."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("soft")
        self.setMinimumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        caption = QHBoxLayout()
        caption.setSpacing(6)
        self.caption = QLabel("СЛУШАЕТ", self)
        self.caption.setStyleSheet(
            f"color: {theme.MUTED_DIM}; font-size: 9px; font-weight: 700; letter-spacing: 1px;"
        )
        caption.addWidget(self.caption)
        self.app = ElidedLabel("Яндекс Музыка", self)
        self.app.setStyleSheet(f"color: {theme.TEXT}; font-size: 10px; font-weight: 600;")
        caption.addWidget(self.app, 1)
        self.small_status = ElidedLabel("", self)
        self.small_status.setObjectName("tiny")
        caption.addWidget(self.small_status)
        layout.addLayout(caption)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.cover = CoverWidget(66, 10, self)
        body.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.details = ElidedLabel("", self)
        self.details.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.state = ElidedLabel("", self)
        self.state.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        self.large_text = ElidedLabel("", self)
        self.large_text.setStyleSheet(f"color: {theme.MUTED_DIM}; font-size: 10px;")
        self.elapsed = QLabel("", self)
        self.elapsed.setObjectName("tiny")
        text.addWidget(self.details)
        text.addWidget(self.state)
        text.addWidget(self.large_text)
        text.addSpacing(3)
        text.addWidget(self.elapsed)
        body.addLayout(text, 1)
        layout.addLayout(body)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        layout.addLayout(self.buttons)
        self.button_one = ElidedLabel("", self)
        self.button_two = ElidedLabel("", self)
        for button in (self.button_one, self.button_two):
            button.setAlignment(Qt.AlignmentFlag.AlignCenter)
            button.setStyleSheet(
                f"color: {theme.TEXT}; background: #232833; border: 1px solid {theme.BORDER};"
                "border-radius: 6px; padding: 5px 9px; font-size: 10px; font-weight: 600;"
            )
            self.buttons.addWidget(button, 1)
        self.buttons.addStretch(1)

    def set_preview(self, data) -> None:
        self.details.set_full_text(data.details or "—")
        self.state.set_full_text(data.state or "")
        self.large_text.set_full_text(data.large_text or "")
        self.small_status.set_full_text(data.small_text)
        self.elapsed.setText("1:12 / 3:34")

    def set_buttons(self, labels: list[str]) -> None:
        for button, label in zip((self.button_one, self.button_two), labels, strict=False):
            button.set_full_text(label)
            button.setVisible(bool(label))


class DiscordPage(Page):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(t("discord.title"), t("discord.subtitle"), parent)
        self._settings = Settings()
        self._build_status()
        self._build_templates()

    # ------------------------------------------------------------------ build

    def _build_status(self) -> None:
        card = Card(padding=18)
        self.presence_toggle = ToggleRow(t("discord.presence"), "", card)
        card.add(self.presence_toggle)

        grid = QHBoxLayout()
        grid.setSpacing(12)
        self.activity_combo = QComboBox(card)
        self.activity_combo.addItem(t("discord.activity_listening"), ActivityKind.LISTENING.value)
        self.activity_combo.addItem(t("discord.activity_playing"), ActivityKind.PLAYING.value)
        grid.addWidget(Field(t("discord.activity"), self.activity_combo, card), 1)

        self.buttons_combo = QComboBox(card)
        self.buttons_combo.addItem(t("discord.buttons_track"), ButtonsMode.TRACK.value)
        self.buttons_combo.addItem(t("discord.buttons_app"), ButtonsMode.APP.value)
        self.buttons_combo.addItem(t("discord.buttons_both"), ButtonsMode.BOTH.value)
        self.buttons_combo.addItem(t("discord.buttons_none"), ButtonsMode.NONE.value)
        grid.addWidget(Field(t("discord.buttons"), self.buttons_combo, card), 1)

        self.pause_combo = QComboBox(card)
        grid.addWidget(Field(t("discord.pause_timeout"), self.pause_combo, card), 1)
        card.add_layout(grid)

        self.pause_toggle = ToggleRow(t("discord.show_paused"), "", card)
        card.add(self.pause_toggle)

        divider = QFrame(card)
        divider.setObjectName("separator")
        divider.setFrameShape(QFrame.Shape.HLine)
        card.add(divider)

        self.lyrics_toggle = ToggleRow(t("discord.lyrics_in_presence"), t("discord.lyrics_hint"), card)
        card.add(self.lyrics_toggle)

        offset_row = QHBoxLayout()
        offset_row.addWidget(Field(t("lyrics.offset"), self._offset_spin(card), card), 0)
        offset_row.addStretch(1)
        card.add_layout(offset_row)

        card.body.setSpacing(12)
        self.add(card)

        self.presence_toggle.switch.toggled.connect(self._on_presence)
        self.show_paused_state = self.pause_toggle.switch
        self.pause_toggle.switch.toggled.connect(self._pause_toggled)
        for combo in (self.activity_combo, self.buttons_combo, self.pause_combo):
            combo.currentIndexChanged.connect(self._refresh)
        self.lyrics_toggle.switch.toggled.connect(self._refresh)
        self.offset_spin.valueChanged.connect(self._refresh)

    def _offset_spin(self, parent: QWidget) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(parent)
        spin.setRange(-30.0, 30.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" с")
        spin.setFixedWidth(110)
        self.offset_spin = spin
        return spin

    def _build_templates(self) -> None:
        card = Card(padding=18)
        header = QHBoxLayout()
        title = QLabel(t("discord.templates"), card)
        title.setObjectName("h2")
        header.addWidget(title)
        header.addStretch(1)
        reset = QPushButton(t("discord.reset_templates"), card)
        reset.setObjectName("ghost")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset_templates)
        header.addWidget(reset)
        card.add_layout(header)

        hint = QLabel(t("discord.templates_hint"), card)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        card.add(hint)

        columns = QHBoxLayout()
        columns.setSpacing(22)
        form = QVBoxLayout()
        form.setSpacing(10)
        self.details_edit = self._template_edit(card, t("discord.details"))
        self.state_edit = self._template_edit(card, t("discord.state"))
        self.large_edit = self._template_edit(card, t("discord.large_text"))
        for edit in (self.details_edit, self.state_edit, self.large_edit):
            form.addWidget(edit["field"])
        self.error_label = QLabel("", card)
        self.error_label.setObjectName("danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        form.addWidget(self.error_label)
        form.addStretch(1)
        columns.addLayout(form, 3)

        preview_column = QVBoxLayout()
        preview_column.setSpacing(6)
        caption = QLabel(t("discord.preview"), card)
        caption.setObjectName("tiny")
        preview_column.addWidget(caption)
        self.preview_widget = DiscordPreview(card)
        preview_column.addWidget(self.preview_widget)
        hint_label = QLabel(t("discord.preview_hint"), card)
        hint_label.setObjectName("tiny")
        hint_label.setWordWrap(True)
        preview_column.addWidget(hint_label)
        preview_column.addStretch(1)
        columns.addLayout(preview_column, 2)
        card.add_layout(columns)
        self.add(card)

    def _template_edit(self, parent: QWidget, label: str) -> dict:
        edit = QLineEdit(parent)
        edit.setMaxLength(128)
        edit.textChanged.connect(self._refresh)
        counter = QLabel("0 / 128", parent)
        counter.setObjectName("tiny")
        counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        row.addWidget(counter, 0)
        holder = QWidget(parent)
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        field = Field(label, holder, parent)
        edit.textChanged.connect(lambda text, c=counter: c.setText(f"{len(text)} / 128"))
        return {"field": field, "edit": edit, "counter": counter}

    # ------------------------------------------------------------------ state

    def _pause_options(self) -> list[tuple[str, int]]:
        return [
            (t("discord.pause_never"), -1),
            (t("discord.pause_seconds", seconds=30), 30),
            (t("discord.pause_seconds", seconds=60), 60),
            (t("discord.pause_seconds", seconds=300), 300),
            (t("discord.pause_seconds", seconds=600), 600),
            (t("discord.pause_seconds", seconds=1800), 1800),
            (t("discord.pause_seconds", seconds=3600), 3600),
        ]

    def _load(self, settings: Settings) -> None:
        self._settings = settings
        self.presence_toggle.switch.setChecked(settings.presence_enabled)
        self.activity_combo.setCurrentIndex(
            max(0, self.activity_combo.findData(settings.activity_type.value))
        )
        self.buttons_combo.setCurrentIndex(
            max(0, self.buttons_combo.findData(settings.buttons.value))
        )
        self.pause_combo.clear()
        options = self._pause_options()
        if settings.pause_timeout not in [value for _label, value in options]:
            options.insert(1, (t("discord.pause_seconds", seconds=settings.pause_timeout), settings.pause_timeout))
        for label, value in options:
            self.pause_combo.addItem(label, value)
        self.pause_combo.setCurrentIndex(max(0, self.pause_combo.findData(settings.pause_timeout)))
        self.pause_toggle.switch.setChecked(settings.show_paused)
        self.pause_combo.setEnabled(settings.show_paused)
        self.lyrics_toggle.switch.setChecked(settings.lyrics_in_presence)
        self.offset_spin.setValue(settings.lyrics_offset)
        self.details_edit["edit"].setText(settings.details_template)
        self.state_edit["edit"].setText(settings.state_template)
        self.large_edit["edit"].setText(settings.large_text_template)
        self._on_presence(settings.presence_enabled)
        self._refresh()

    def _on_presence(self, enabled: bool) -> None:
        for widget in (self.activity_combo, self.buttons_combo):
            widget.setEnabled(enabled)
        self.pause_toggle.setEnabled(enabled)
        self.lyrics_toggle.setEnabled(enabled)
        self.offset_spin.setEnabled(enabled and self.lyrics_toggle.switch.isChecked())
        if not self._loading:
            self._refresh()

    def _pause_toggled(self, enabled: bool) -> None:
        self.pause_combo.setEnabled(enabled and self.presence_toggle.switch.isChecked())
        self._refresh()

    def _draft(self) -> Settings:
        return replace(
            self._settings,
            presence_enabled=self.presence_toggle.switch.isChecked(),
            activity_type=ActivityKind(self.activity_combo.currentData()),
            buttons=ButtonsMode(self.buttons_combo.currentData()),
            pause_timeout=int(self.pause_combo.currentData() or 300),
            show_paused=self.pause_toggle.switch.isChecked(),
            lyrics_in_presence=self.lyrics_toggle.switch.isChecked(),
            lyrics_offset=self.offset_spin.value(),
            details_template=self.details_edit["edit"].text(),
            state_template=self.state_edit["edit"].text(),
            large_text_template=self.large_edit["edit"].text(),
        )

    def _refresh(self) -> None:
        draft = self._draft()
        data = preview(draft)
        self.preview_widget.set_preview(data)
        labels = []
        if draft.buttons in (ButtonsMode.TRACK, ButtonsMode.BOTH):
            labels.append(t("presence.browser"))
        if draft.buttons in (ButtonsMode.APP, ButtonsMode.BOTH):
            labels.append(t("presence.app"))
        self.preview_widget.set_buttons(labels)
        self.offset_spin.setEnabled(
            self.presence_toggle.switch.isChecked() and self.lyrics_toggle.switch.isChecked()
        )
        self._validate_fields()
        if not self._loading:
            self.notify()

    def _validate_fields(self) -> str | None:
        errors = []
        for key, label, required in (
            (self.details_edit, t("discord.details"), True),
            (self.state_edit, t("discord.state"), True),
            (self.large_edit, t("discord.large_text"), False),
        ):
            edit = key["edit"]
            text = edit.text()
            message = validate_template(text) if (required or text.strip()) else None
            if message:
                if message == t("discord.invalid_template"):
                    text = f"{label}: {t('discord.invalid_template')}"
                else:
                    text = f"{label}: {t('discord.unknown_fields', fields=message)}"
                errors.append(text)
                edit.setStyleSheet(f"border-color: {theme.RED};")
            else:
                edit.setStyleSheet("")
        if errors:
            self.error_label.setText("\n".join(errors))
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)
        return errors[0] if errors else None

    def validate(self) -> str | None:
        return self._validate_fields()

    def apply_to(self, settings: Settings) -> Settings:
        draft = self._draft()
        return replace(
            settings,
            presence_enabled=draft.presence_enabled,
            activity_type=draft.activity_type,
            buttons=draft.buttons,
            pause_timeout=draft.pause_timeout,
            show_paused=draft.show_paused,
            lyrics_in_presence=draft.lyrics_in_presence,
            lyrics_offset=draft.lyrics_offset,
            details_template=draft.details_template,
            state_template=draft.state_template,
            large_text_template=draft.large_text_template,
        )

    def _reset_templates(self) -> None:
        self.details_edit["edit"].setText(DEFAULT_DETAILS)
        self.state_edit["edit"].setText(DEFAULT_STATE)
        self.large_edit["edit"].setText(DEFAULT_LARGE_TEXT)
