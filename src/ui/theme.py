"""
FALAI Theme - PySide6/Qt Stylesheet
Premium SaaS Aesthetics - Inspired by WhisperFlow
"""

_THEME_TEMPLATE = """
/* ===== GLOBAL STYLES ===== */
QMainWindow, QDialog, QWidget {
    background-color: __BACKGROUND__;
    color: __FOREGROUND__;
    font-family: "Manrope", "Inter", "SF Pro Display", "Segoe UI", -apple-system, sans-serif;
    font-size: 14px;
}

/* ===== FRAMES & CARDS ===== */
QFrame {
    background-color: transparent;
    border: none;
}

QFrame#card, QFrame[frameShape="1"] {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 16px;
}

/* ===== LABELS ===== */
QLabel {
    background-color: transparent;
    color: __FOREGROUND__;
}

QLabel[class="title"], QLabel#pageTitle {
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.5px;
    color: __FOREGROUND__;
}

QLabel[class="subtitle"] {
    font-size: 14px;
    color: __FOREGROUND_DIM__;
    font-weight: 400;
}

QLabel[class="status"] {
    font-size: 15px;
    font-weight: 600;
}

QLabel#sectionHeader {
    font-size: 11px;
    font-weight: 700;
    color: __FOREGROUND_DIM__;
    letter-spacing: 1px;
}

/* ===== ONBOARDING ===== */
QWidget#onboardingHeader {
    background-color: transparent;
}

QLabel#onboardingStepTitle {
    font-size: 22px;
    font-weight: 700;
    color: __FOREGROUND__;
}

QLabel#onboardingStepCounter {
    font-size: 12px;
    font-weight: 600;
    color: __FOREGROUND_DIM__;
}

QFrame#onboardingStepIndicator {
    background-color: __DIVIDER__;
    border-radius: 2px;
    min-height: 4px;
}

QFrame#onboardingStepIndicator[active="true"] {
    background-color: __ACCENT__;
}

QWidget#onboardingContent {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 16px;
}

QLabel#onboardingHint {
    color: __FOREGROUND_DIM__;
    font-size: 14px;
}

/* ===== BUTTONS ===== */
QPushButton {
    background-color: __ACCENT__;
    color: __FOREGROUND_ON_ACCENT__;
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: __ACCENT_HOVER__;
}

QPushButton:pressed {
    background-color: __ACCENT_PRESSED__;
}

QPushButton:disabled {
    background-color: __DISABLED_BG__;
    color: __FOREGROUND_DIM__;
}

QPushButton#primaryButton {
    background-color: __ACCENT__;
    border-radius: 12px;
    padding: 14px 28px;
    font-size: 15px;
}

QPushButton#primaryButton:hover {
    background-color: __ACCENT_HOVER__;
}

QPushButton#secondaryButton {
    background-color: transparent;
    border: 1px solid __BORDER__;
    color: __FOREGROUND__;
    border-radius: 10px;
    padding: 12px 24px;
}

QPushButton#secondaryButton:hover {
    background-color: __NAV_HOVER__;
    border-color: __ACCENT__;
}

QPushButton#ghostButton {
    background-color: transparent;
    border: 1px solid __BORDER__;
    color: __FOREGROUND__;
}

QPushButton#ghostButton:hover {
    background-color: __NAV_HOVER__;
    border-color: __ACCENT__;
}

QPushButton[class="danger"] {
    background-color: __DANGER__;
}

QPushButton[class="danger"]:hover {
    background-color: __DANGER_HOVER__;
}

QPushButton[class="icon"], QPushButton#iconButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px;
    font-size: 16px;
    color: __FOREGROUND_DIM__;
}

QPushButton[class="icon"]:hover, QPushButton#iconButton:hover {
    background-color: __NAV_HOVER__;
    color: __FOREGROUND__;
}

/* ===== TEXT INPUT ===== */
QLineEdit {
    background-color: __INPUT_BG__;
    color: __FOREGROUND__;
    border: 1px solid __INPUT_BORDER__;
    border-radius: 10px;
    padding: 12px 16px;
    font-size: 14px;
    selection-background-color: __ACCENT__;
}

QLineEdit:focus {
    border: 2px solid __ACCENT__;
    padding: 11px 15px;
}

QLineEdit:disabled {
    background-color: __BACKGROUND__;
    color: __FOREGROUND_DIM__;
}

QLineEdit::placeholder {
    color: __FOREGROUND_DIM__;
}

/* ===== TEXT AREA ===== */
QPlainTextEdit, QTextEdit {
    background-color: __INPUT_BG__;
    color: __FOREGROUND__;
    border: 1px solid __INPUT_BORDER__;
    border-radius: 12px;
    padding: 14px 16px;
    font-size: 14px;
    selection-background-color: __ACCENT__;
}

QPlainTextEdit:focus, QTextEdit:focus {
    border: 2px solid __ACCENT__;
    padding: 13px 15px;
}

/* ===== CHECKBOXES ===== */
QCheckBox {
    color: __FOREGROUND__;
    spacing: 10px;
    font-size: 14px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 2px solid __BORDER__;
    background-color: __INPUT_BG__;
}

QCheckBox::indicator:checked {
    background-color: __ACCENT__;
    border-color: __ACCENT__;
}

QCheckBox::indicator:hover {
    border-color: __ACCENT__;
}

/* ===== TOGGLE SWITCH ===== */
QCheckBox#switch::indicator {
    width: 48px;
    height: 26px;
    border-radius: 13px;
    border: none;
    background-color: __SWITCH_OFF__;
}

QCheckBox#switch::indicator:checked {
    background-color: __ACCENT__;
}

QCheckBox#switch::indicator:hover {
    background-color: __SWITCH_OFF_HOVER__;
}

QCheckBox#switch::indicator:checked:hover {
    background-color: __ACCENT_HOVER__;
}

/* ===== RADIO BUTTONS ===== */
QRadioButton {
    color: __FOREGROUND__;
    spacing: 10px;
}

QRadioButton::indicator {
    width: 20px;
    height: 20px;
    border-radius: 10px;
    border: 2px solid __BORDER__;
    background-color: __INPUT_BG__;
}

QRadioButton::indicator:checked {
    background-color: __ACCENT__;
    border-color: __ACCENT__;
}

QRadioButton::indicator:hover {
    border-color: __ACCENT__;
}

/* ===== SCROLL AREA ===== */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background-color: __SCROLLBAR__;
    border-radius: 4px;
    min-height: 40px;
}

QScrollBar::handle:vertical:hover {
    background-color: __SCROLLBAR_HOVER__;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background-color: transparent;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 8px;
    margin: 2px 4px;
}

QScrollBar::handle:horizontal {
    background-color: __SCROLLBAR__;
    border-radius: 4px;
    min-width: 40px;
}

QScrollBar::handle:horizontal:hover {
    background-color: __SCROLLBAR_HOVER__;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background-color: transparent;
}

/* ===== GROUP BOX ===== */
QGroupBox {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
    margin-top: 16px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: __FOREGROUND__;
    font-size: 14px;
}

/* ===== COMBO BOX ===== */
QComboBox {
    background-color: __INPUT_BG__;
    color: __FOREGROUND__;
    border: 1px solid __INPUT_BORDER__;
    border-radius: 10px;
    padding: 10px 14px;
    min-width: 120px;
    font-size: 14px;
}

QComboBox:hover {
    border-color: __ACCENT__;
}

QComboBox:focus {
    border: 2px solid __ACCENT__;
}

QComboBox::drop-down {
    border: none;
    padding-right: 12px;
}

QComboBox QAbstractItemView {
    background-color: __CARD_BG__;
    color: __FOREGROUND__;
    selection-background-color: __NAV_HOVER__;
    selection-color: __FOREGROUND__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 8px;
    padding: 4px;
}

/* ===== MESSAGE BOX ===== */
QMessageBox {
    background-color: __BACKGROUND__;
}

QMessageBox QLabel {
    color: __FOREGROUND__;
}

/* ===== SIDEBAR ===== */
QFrame#sidebar {
    background-color: __SIDEBAR_BG__;
    border-right: 1px solid __SIDEBAR_BORDER__;
}

QLabel#brandTitle {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: __ACCENT__;
}

QLabel#brandSubtitle {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QPushButton#navButton {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 12px 16px;
    text-align: left;
    color: __FOREGROUND_DIM__;
    font-weight: 500;
    font-size: 14px;
}

QPushButton#navButton:hover {
    background-color: __NAV_HOVER__;
    color: __FOREGROUND__;
}

QPushButton#navButton:checked {
    background-color: __NAV_SELECTED_BG__;
    color: __ACCENT__;
    font-weight: 600;
}

QPushButton#navButton[collapsed="true"] {
    text-align: center;
    padding: 12px;
}

/* ===== PREMIUM CARDS ===== */
QFrame#card {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 16px;
}

QFrame#premiumCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 16px;
}

QLabel#statLabel {
    font-size: 13px;
    color: __FOREGROUND_DIM__;
    font-weight: 500;
}

QFrame#statCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
}

QFrame#statsKpiCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 14px;
}

QLabel#statTitle {
    font-size: 12px;
    font-weight: 600;
    color: __FOREGROUND__;
}

QLabel#statValue {
    font-size: 26px;
    font-weight: 700;
    color: __FOREGROUND__;
}

QLabel#statSubtitle {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#statDesc {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#statIcon {
    font-size: 14px;
}

QPushButton#statInfoBadge {
    color: __FOREGROUND_DIM__;
    background: transparent;
    border: none;
    padding: 0px 2px;
    font-size: 12px;
}

QPushButton#statInfoBadge:hover {
    color: __FOREGROUND__;
}

QWidget#kpiBand {
    background: transparent;
}

QWidget#kpiItem {
    background: transparent;
    padding: 0px 8px 0px 8px;
}

QWidget#kpiItem[divider="true"] {
    border-left: 1px solid __DIVIDER__;
}

QLabel#kpiTitle {
    font-size: 12px;
    font-weight: 600;
    color: __FOREGROUND_DIM__;
    letter-spacing: 0.3px;
}

QLabel#kpiValue {
    font-size: 28px;
    font-weight: 700;
    color: __FOREGROUND__;
    letter-spacing: -0.5px;
}

QLabel#kpiSubtext {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QPushButton#kpiInfoBadge {
    color: __FOREGROUND_DIM__;
    background: transparent;
    border: none;
    padding: 0px 2px;
    font-size: 12px;
}

QPushButton#kpiInfoBadge:hover {
    color: __FOREGROUND__;
}

QLabel#statsMeta {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#chartValueLabel {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#chartDateLabel {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QWidget#chartColumnToday {
    border-bottom: 2px solid __ACCENT__;
}

QToolTip {
    background-color: __CARD_BG__;
    color: __FOREGROUND__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 6px;
    padding: 6px 8px;
}


/* ===== PILLS & STATUS ===== */
QWidget#statusPill {
    background-color: __PILL_BG__;
    border: 1px solid __BORDER__;
    border-radius: 20px;
}

QWidget#statusBadgeMini {
    background-color: __PILL_BG__;
    border: 1px solid __BORDER__;
    border-radius: 9px;
}

QLabel#statusPrimary {
    font-size: 14px;
    font-weight: 600;
}

QLabel#statusSecondary {
    font-size: 12px;
    color: __FOREGROUND_DIM__;
}

QLabel#statusBadgeText {
    font-size: 11px;
    font-weight: 600;
    color: __FOREGROUND_DIM__;
}

QLabel#mutedLabel {
    color: __FOREGROUND_DIM__;
    font-size: 10px;
    font-weight: 500;
}

/* ===== SETTINGS ===== */
QLabel#settingTitle {
    font-size: 13px;
    font-weight: 600;
    color: __FOREGROUND__;
}

QLabel#settingDescription {
    font-size: 12px;
    color: __FOREGROUND_DIM__;
}

QWidget#settingRow {
    border-bottom: none;
    border-radius: 8px;
}

QWidget#settingRow[last="true"] {
    border-bottom: none;
}

QWidget#settingRow:hover {
    background-color: __HOVER_BG__;
}

QWidget#settingRow:focus-within {
    background-color: __HOVER_BG__;
}

QFrame#settingsSection {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    border-bottom: 1px solid __DIVIDER__;
    padding-bottom: 6px;
}

QFrame#settingsSection[last="true"] {
    border-bottom: none;
}

QLabel#settingsSectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: __FOREGROUND__;
}

/* ===== ONBOARDING PREMIUM ===== */
QLabel#onboardingHeroTitle {
    font-size: 32px;
    font-weight: 800;
    letter-spacing: -1px;
    color: __FOREGROUND__;
}

QLabel#onboardingHeroSubtitle {
    font-size: 16px;
    color: __FOREGROUND_DIM__;
    font-weight: 400;
    line-height: 1.4;
}

QFrame#onboardingCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 20px;
}

QLabel#keycap {
    background-color: __INPUT_BG__;
    border: 1px solid __BORDER__;
    border-radius: 6px;
    padding: 4px 8px;
    font-family: "Consolas", "Monaco", monospace;
    font-size: 12px;
    font-weight: 700;
    color: __FOREGROUND__;
}

QFrame#testArea {
    background-color: __INPUT_BG__;
    border: 1px dashed __BORDER__;
    border-radius: 12px;
}

QFrame#testArea[status="active"] {
    border: 1px solid __ACCENT__;
    background-color: __HOVER_BG__;
}

QProgressBar {
    background-color: __DIVIDER__;
    border-radius: 2px;
    min-height: 4px;
    max-height: 4px;
}

QProgressBar::chunk {
    background-color: __ACCENT__;
    border-radius: 2px;
}

/* (Plans styles consolidated in token section below) */

/* ===== SEGMENT CONTROL ===== */
QWidget#segmentGroup {
    background-color: __PILL_BG__;
    border: 1px solid __BORDER__;
    border-radius: 10px;
    min-height: 30px;
}

QPushButton#segmentButton {
    background-color: transparent;
    color: __FOREGROUND_DIM__;
    border: none;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    min-width: 72px;
}

QPushButton#segmentButton[segment="left"] {
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
}

QPushButton#segmentButton[segment="right"] {
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

QPushButton#segmentButton:checked {
    background-color: __ACCENT__;
    color: __FOREGROUND_ON_ACCENT__;
    font-weight: 600;
}

QPushButton#segmentButton:hover {
    color: __FOREGROUND__;
}

QPushButton#segmentButton:disabled {
    color: __FOREGROUND_DIM__;
}

/* ===== HISTORY ===== */
QWidget#historyHeader {
    background: transparent;
}

QLabel#historyCount {
    color: __FOREGROUND_DIM__;
    font-size: 12px;
}

QLineEdit#historySearch {
    min-height: 32px;
    padding: 6px 10px;
}

QPushButton#historyFilterToggle {
    background-color: __BACKGROUND_LIGHT__;
    border: 1px solid __BORDER__;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 12px;
    color: __FOREGROUND__;
}

QPushButton#historyFilterToggle:checked {
    border-color: __ACCENT__;
    color: __ACCENT__;
}

QLabel#historyChip {
    background-color: __BACKGROUND_LIGHT__;
    border: 1px solid __BORDER__;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#homeHistoryTitle {
    color: __FOREGROUND__;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.2px;
}

QLabel#homeHistoryCount {
    color: __FOREGROUND_DIM__;
    font-size: 12px;
    font-weight: 500;
}

QWidget#homeHistoryEmpty {
    background: transparent;
}

QLabel#homeHistoryEmptyTitle {
    color: __FOREGROUND__;
    font-size: 13px;
    font-weight: 600;
}

QLabel#homeHistoryEmptySubtitle {
    color: __FOREGROUND_DIM__;
    font-size: 12px;
}

QWidget#historyPreviewItem {
    background: transparent;
}

QLabel#historyPreviewDate {
    color: __FOREGROUND__;
    font-size: 13px;
    font-weight: 600;
}

QLabel#historyPreviewTime {
    color: __FOREGROUND_DIM__;
    font-size: 11px;
    font-weight: 500;
}

QFrame#historyPreviewDot {
    background-color: __ACCENT__;
    border-radius: 4px;
}

QFrame#historyPreviewGuide {
    background-color: __DIVIDER__;
    border-radius: 1px;
}

QFrame#historyPreviewCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
}

QFrame#historyPreviewCard:hover {
    border-color: __ACCENT__;
}

QLabel#historyPreviewText {
    color: __FOREGROUND__;
    font-size: 14px;
}

QLabel#historyPreviewBadge {
    background-color: __PILL_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#historyPreviewBadge[variant="corrected"] {
    background-color: rgba(16, 185, 129, 0.12);
    border-color: rgba(16, 185, 129, 0.35);
    color: __ACCENT__;
}

QPushButton#historyPreviewAction {
    background: transparent;
    border: 1px solid __CARD_BORDER__;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    color: __FOREGROUND__;
}

QPushButton#historyPreviewAction:hover {
    border-color: __ACCENT__;
    color: __ACCENT__;
}

QPushButton#historyPreviewActionPrimary {
    background-color: __ACCENT__;
    border: 1px solid __ACCENT__;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    color: __FOREGROUND_ON_ACCENT__;
}

QPushButton#historyPreviewActionPrimary:hover {
    background-color: __ACCENT_HOVER__;
    border-color: __ACCENT_HOVER__;
}

QLabel#historyPreviewToast {
    color: __ACCENT__;
    font-size: 11px;
    font-weight: 600;
}

QFrame#historyEntry {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 14px;
}

QFrame#historyEntry:hover {
    border-color: __ACCENT__;
}

QLabel#historyMeta {
    color: __FOREGROUND_DIM__;
    font-size: 12px;
}

QLabel#historyText {
    color: __FOREGROUND__;
    font-size: 15px;
}

QCalendarWidget {
    background-color: __BACKGROUND_LIGHT__;
    border: 1px solid __BORDER__;
    border-radius: 12px;
}

QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: __BACKGROUND_LIGHT__;
    border-bottom: 1px solid __BORDER__;
}

QCalendarWidget QToolButton {
    color: __FOREGROUND__;
    font-weight: 600;
    padding: 6px;
    background-color: transparent;
}

QCalendarWidget QMenu {
    background-color: __BACKGROUND_LIGHT__;
    border: 1px solid __BORDER__;
}

QCalendarWidget QSpinBox {
    color: __FOREGROUND__;
    background-color: __BACKGROUND_LIGHT__;
    selection-background-color: __ACCENT__;
    selection-color: __FOREGROUND_ON_ACCENT__;
}

QCalendarWidget QAbstractItemView:enabled {
    color: __FOREGROUND__;
    font-size: 12px;
    selection-background-color: __ACCENT__;
    selection-color: __FOREGROUND_ON_ACCENT__;
    outline: none;
    gridline-color: __DIVIDER__;
    background-color: __BACKGROUND_LIGHT__;
}

QCalendarWidget QAbstractItemView:disabled {
    color: __FOREGROUND_DIM__;
    background-color: __BACKGROUND_LIGHT__;
}

QLabel#historyBadge {
    background-color: __PILL_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#historyBadge[variant="corrected"] {
    background-color: rgba(16, 185, 129, 0.12);
    border-color: rgba(16, 185, 129, 0.35);
    color: __ACCENT__;
}

QLabel#historyBadge[variant="duration"] {
    color: __ACCENT__;
}

QPushButton#historyAction {
    background-color: transparent;
    border: 1px solid __CARD_BORDER__;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    color: __FOREGROUND__;
}

QPushButton#historyAction:hover {
    border-color: __ACCENT__;
    color: __ACCENT__;
}

QLabel#historyToast {
    color: __ACCENT__;
    font-size: 11px;
}

/* ===== PLANS ===== */

/* Page Header */
QLabel#plansPageTitle {
    font-size: 28px;
    font-weight: 800;
    color: __FOREGROUND__;
    letter-spacing: -0.5px;
}

QLabel#plansPageSubtitle {
    font-size: 15px;
    font-weight: 400;
    color: __FOREGROUND_DIM__;
}

/* Trial Banner - Compact Pill */
QFrame#trialBannerCard {
    background-color: __ACCENT__;
    border: none;
    border-radius: 999px;
}

QLabel#trialBannerIcon {
    background: transparent;
}

QLabel#trialBannerTitle {
    color: __FOREGROUND_ON_ACCENT__;
    font-size: 14px;
    font-weight: 700;
}

QLabel#trialBannerSep {
    font-size: 14px;
    font-weight: 700;
    color: rgba(255, 255, 255, 0.5);
}

QLabel#trialBannerDetail {
    color: __FOREGROUND_ON_ACCENT__;
    font-size: 13px;
    font-weight: 500;
}

QPushButton#trialBannerButton {
    background-color: __FOREGROUND_ON_ACCENT__;
    color: __ACCENT__;
    border: none;
    border-radius: 18px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#trialBannerButton:hover {
    background-color: __BACKGROUND_LIGHT__;
}

/* Pricing Cards */
QFrame#pricingCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 20px;
}

QFrame#pricingCard[featured="true"] {
    border: 2px solid __ACCENT__;
    background-color: __CARD_BG__;
}

QLabel#planName {
    font-size: 22px;
    font-weight: 800;
    color: __FOREGROUND__;
    letter-spacing: -0.5px;
}

QLabel#planPrice {
    font-size: 38px;
    font-weight: 800;
    color: __ACCENT__;
    letter-spacing: -1.5px;
}

QLabel#planPeriod {
    font-size: 14px;
    font-weight: 500;
    color: __FOREGROUND_DIM__;
}

QLabel#planTag {
    font-size: 13px;
    font-weight: 500;
    color: __FOREGROUND_DIM__;
}

QFrame#planDivider {
    background-color: __DIVIDER__;
    border: none;
}

QLabel#planFeature {
    font-size: 13px;
    font-weight: 500;
    color: __FOREGROUND_DIM__;
}

QLabel#planFeaturePro {
    font-size: 13px;
    font-weight: 600;
    color: __FOREGROUND__;
}

QLabel#featureCheckIcon {
    background: transparent;
}

QWidget#planFeatureRow {
    background: transparent;
}

QLabel#planIncludesLabel {
    font-size: 12px;
    font-weight: 600;
    color: __ACCENT__;
    font-style: italic;
}

QLabel#planMicrocopy {
    font-size: 11px;
    color: __FOREGROUND_DIM__;
}

QLabel#planFounder {
    font-size: 11px;
    font-weight: 700;
    color: __WARNING__;
}

QWidget#featuredBadge {
    background-color: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.25);
    border-radius: 8px;
}

QLabel#featuredBadgeText {
    font-size: 10px;
    font-weight: 800;
    color: __ACCENT__;
    letter-spacing: 1px;
    background: transparent;
}

/* Plan Buttons */
QPushButton#primaryPlanButton {
    background-color: __ACCENT__;
    color: __FOREGROUND_ON_ACCENT__;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
}

QPushButton#primaryPlanButton:hover {
    background-color: __ACCENT_HOVER__;
}

QPushButton#primaryPlanButton:pressed {
    background-color: __ACCENT_PRESSED__;
}

QPushButton#secondaryPlanButton {
    background-color: transparent;
    color: __ACCENT__;
    border: 2px solid __ACCENT__;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
}

QPushButton#secondaryPlanButton:hover {
    background-color: rgba(16, 185, 129, 0.08);
}

QPushButton#secondaryPlanButton:pressed {
    background-color: rgba(16, 185, 129, 0.15);
}

/* Trust Section */
QLabel#trustLabel {
    font-size: 12px;
    font-weight: 500;
    color: __FOREGROUND_DIM__;
}

QLabel#trustSep {
    font-size: 12px;
    color: __FOREGROUND_DIM__;
}

/* ===== TABLE / LIST ===== */
QTableWidget, QListWidget {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
    gridline-color: __DIVIDER__;
}

QTableWidget::item, QListWidget::item {
    padding: 12px;
    border-bottom: 1px solid __DIVIDER__;
}

QTableWidget::item:selected, QListWidget::item:selected {
    background-color: __NAV_HOVER__;
}

QHeaderView::section {
    background-color: __CARD_BG__;
    color: __FOREGROUND_DIM__;
    font-weight: 600;
    font-size: 12px;
    padding: 12px;
    border: none;
    border-bottom: 1px solid __DIVIDER__;
}

/* ===== TOOLTIP ===== */
QToolTip {
    background-color: __TOOLTIP_BG__;
    color: __FOREGROUND__;
    border: 1px solid __BORDER__;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}

/* ===== TAB WIDGET ===== */
QTabWidget::pane {
    border: none;
    background-color: transparent;
}

QTabBar::tab {
    background-color: transparent;
    color: __FOREGROUND_DIM__;
    padding: 12px 20px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:hover {
    color: __FOREGROUND__;
}

QTabBar::tab:selected {
    color: __ACCENT__;
    border-bottom: 2px solid __ACCENT__;
    font-weight: 600;
}

/* ===== PROGRESS BAR ===== */
QProgressBar {
    background-color: __PROGRESS_BG__;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: __ACCENT__;
    border-radius: 4px;
}

/* ===== MENU ===== */
QMenu {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
    padding: 8px;
}

QMenu::item {
    padding: 10px 20px;
    border-radius: 8px;
}

QMenu::item:selected {
    background-color: __NAV_HOVER__;
}

QMenu::separator {
    height: 1px;
    background-color: __DIVIDER__;
    margin: 8px 0;
}

/* ===== RECORD BUTTON ===== */
QPushButton#recordButton {
    background-color: __ACCENT__;
    border: none;
    border-radius: 44px;
    font-size: 32px;
    color: __FOREGROUND_ON_ACCENT__;
}

QPushButton#recordButton:hover {
    background-color: __ACCENT_HOVER__;
}

QPushButton#recordButton:pressed {
    background-color: __ACCENT_PRESSED__;
}

QPushButton#recordButton[recording="true"] {
    background-color: __RECORDING__;
}

/* ===== QUICK ACTION CARDS ===== */
QFrame#quickActionCard {
    background-color: __CARD_BG__;
    border: 1px solid __CARD_BORDER__;
    border-radius: 12px;
}

QFrame#quickActionCard:hover {
    border-color: __ACCENT__;
    background-color: __HOVER_BG__;
}

QLabel#quickActionIcon {
    font-size: 18px;
    color: __ACCENT__;
}

QLabel#quickActionLabel {
    font-size: 12px;
    font-weight: 500;
    color: __FOREGROUND__;
}

/* ===== STATUS DOT ===== */
QFrame#statusDot {
    background-color: __ACCENT__;
    border-radius: 5px;
}

/* ===== DIVIDER ===== */
QFrame#divider {
    background-color: __DIVIDER__;
}

/* ===== PRICING CARDS (legacy compat) ===== */
QFrame#pricingCardFeatured {
    background-color: __CARD_BG__;
    border: 2px solid __ACCENT__;
    border-radius: 20px;
}

/* ===== ACCENT VALUES ===== */
QLabel#accentValue {
    color: __ACCENT__;
}
"""

THEME_COLORS = {
    "dark": {
        "background": "#0B1220",
        "background_light": "#111827",
        "foreground": "#F8FAFC",
        "foreground_dim": "#94A3B8",
        "foreground_on_accent": "#FFFFFF",
        "accent": "#10B981",
        "accent_hover": "#0F9F70",
        "accent_pressed": "#064E3B",
        "danger": "#DC2626",
        "danger_hover": "#B91C1C",
        "warning": "#F59E0B",
        "success": "#059669",
        "error": "#DC2626",
        "border": "#2F3442",
        "border_hover": "#4B5563",
        "recording": "#DC2626",
        "processing": "#F59E0B",
        "sidebar_bg": "#111827",  # Matching background for seamless look, or slightly different if desired
        "sidebar_border": "#374151",
        "card_bg": "#171A24",
        "card_border": "#2A2F3C",
        "pill_bg": "#1F2937",
        "nav_hover": "#374151",
        "nav_selected_bg": "#0D2920",
        "input_bg": "#141418",
        "input_border": "#2A2A35",
        "switch_off": "#3A3A48",
        "switch_off_hover": "#4A4A58",
        "disabled_bg": "#2A2A35",
        "divider": "#232836",
        "scrollbar": "#2A2A35",
        "scrollbar_hover": "#3A3A48",
        "tooltip_bg": "#1A1A22",
        "progress_bg": "#2A2A35",
        "hover_bg": "#1A1A22",
    },
    "beige": {
        "background": "#FAFAF8",
        "background_light": "#FFFFFF",
        "foreground": "#1A1A1F",
        "foreground_dim": "#6B6B7B",
        "foreground_on_accent": "#FFFFFF",
        "accent": "#10B981",
        "accent_hover": "#0F9F70",
        "accent_pressed": "#065F46",
        "danger": "#DC2626",
        "danger_hover": "#B91C1C",
        "warning": "#D97706",
        "success": "#059669",
        "error": "#EF4444",
        "border": "#E5E5E8",
        "border_hover": "#D4D4D8",
        "recording": "#DC2626",
        "processing": "#D97706",
        "sidebar_bg": "#F5F5F3",
        "sidebar_border": "#E8E8EB",
        "card_bg": "#F4F4F2",
        "card_border": "#D9D9E0",
        "pill_bg": "#F5F5F3",
        "nav_hover": "#EBEBEF",
        "nav_selected_bg": "#D1FAE5",
        "input_bg": "#FFFFFF",
        "input_border": "#E5E5E8",
        "switch_off": "#D4D4D8",
        "switch_off_hover": "#B8B8C0",
        "disabled_bg": "#F5F5F3",
        "divider": "#D9D9E0",
        "scrollbar": "#D4D4D8",
        "scrollbar_hover": "#B8B8C0",
        "tooltip_bg": "#FFFFFF",
        "progress_bg": "#E8E8EB",
        "hover_bg": "#F5F5F3",
    },
}


def _build_theme(colors: dict) -> str:
    theme = _THEME_TEMPLATE
    for key, value in colors.items():
        theme = theme.replace(f"__{key.upper()}__", value)
    return theme


DARK_THEME = _build_theme(THEME_COLORS["dark"])
BEIGE_THEME = _build_theme(THEME_COLORS["beige"])


def get_colors(theme: str) -> dict:
    return THEME_COLORS.get(theme, THEME_COLORS["dark"]).copy()


def get_stylesheet(theme: str) -> str:
    if theme == "beige":
        return BEIGE_THEME
    return DARK_THEME


COLORS = THEME_COLORS["dark"].copy()

FONT_SIZES = {
    "xs": 11,
    "sm": 13,
    "base": 14,
    "md": 16,
    "lg": 18,
    "xl": 20,
    "2xl": 24,
    "3xl": 32,
}

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "2xl": 32,
}

RADIUS = {
    "sm": 6,
    "md": 10,
    "lg": 16,
    "xl": 20,
    "full": 999,
}

FLOATING_BAR_STYLE = """
QWidget#floatingBar {
    background-color: rgba(18, 18, 24, 0.94);
    border: 1.5px solid rgba(255, 255, 255, 0.10);
    border-radius: 24px;
}

QLabel#indicator {
    font-size: 20px;
    background-color: transparent;
}

QLabel#statusLabel {
    font-size: 14px;
    font-weight: 600;
    color: #ffffff;
    background-color: transparent;
}
"""

SETTINGS_STYLE = """
QFrame#section {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 16px;
}

QLabel#sectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #FFFFFF;
}

QLabel#sectionSubtitle {
    font-size: 12px;
    color: #8B8B9E;
}
"""

HISTORY_STYLE = """
QFrame#historyEntry {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 12px;
}

QFrame#historyEntry:hover {
    background-color: #1A1A22;
    border-color: #10B981;
}

QLabel#timestamp {
    font-size: 12px;
    color: #8B8B9E;
}

QLabel#duration {
    font-size: 12px;
    color: #10B981;
}
"""

STATS_STYLE = """
QFrame#kpiCard {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 16px;
}

QLabel#kpiValue {
    font-size: 36px;
    font-weight: 700;
    color: #FFFFFF;
}

QLabel#kpiLabel {
    font-size: 13px;
    color: #8B8B9E;
    font-weight: 500;
}

QFrame#chartContainer {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 16px;
}
"""

RECORD_BUTTON_STYLE = """
QPushButton#recordButton {
    background-color: #10B981;
    border: none;
    border-radius: 40px;
    min-width: 80px;
    min-height: 80px;
    max-width: 80px;
    max-height: 80px;
}

QPushButton#recordButton:hover {
    background-color: #0EA672;
}

QPushButton#recordButton:pressed {
    background-color: #0D9668;
}

QPushButton#recordButton[recording="true"] {
    background-color: #EF4444;
}

QPushButton#recordButton[recording="true"]:hover {
    background-color: #DC2626;
}
"""

HOME_PAGE_STYLE = """
QFrame#homeCard {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 20px;
}

QLabel#homeTitle {
    font-size: 28px;
    font-weight: 700;
    color: #FFFFFF;
}

QLabel#homeSubtitle {
    font-size: 16px;
    color: #8B8B9E;
}

QLabel#hotkeyBadge {
    background-color: __INPUT_BG__;
    border: 1px solid __INPUT_BORDER__;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 600;
    color: __ACCENT__;
}
"""

PLAN_CARD_STYLE = """
QFrame#planCard {
    background-color: #141418;
    border: 1px solid #252530;
    border-radius: 16px;
}

QFrame#planCard[featured="true"] {
    border: 2px solid #10B981;
    background-color: #0D2920;
}

QLabel#planBadge {
    background-color: #10B981;
    color: #FFFFFF;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 700;
}
"""
