"""Menu styles, including the original pre-Liquid-Glass appearance."""

CLASSIC_MENU = """
QMenuBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fc, stop:1 #f0f2f8);
                color: #1e2532;
                padding: 3px 10px;
                min-height: 40px;
                border-bottom: 2px solid qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7b96f8, stop:0.35 #4361ee, stop:0.65 #4361ee, stop:1 #7b96f8);
                font-size: 14px;
                spacing: 3px;
            }
            QMenuBar::item {
                padding: 5px 14px;
                background: transparent;
                border-radius: 6px;
                border: 1.5px solid transparent;
                color: #2e3555;
                margin: 0 1px;
            }
            QMenuBar::item:selected {
                background: #eef2ff;
                color: #4361ee;
                border-color: #c5d0f8;
            }
            QMenuBar::item:pressed {
                background: #4361ee;
                color: #ffffff;
                border-color: #3451d1;
            }
"""

LIQUID_MENU = """
QMenuBar {
    background: #e9edf2;
    color: #263546;
    padding: 4px 8px;
    min-height: 0px;
    border-bottom: 1px solid #ced7e1;
    font-size: 14px;
    spacing: 4px;
}
QMenuBar::item {
    padding: 12px 20px;
    background: transparent;
    color: transparent;
    margin: 0;
    border: none;
}
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: transparent;
    color: transparent;
}
"""

CLASSIC_BUTTONS = {'_apply_btn': 'QPushButton { padding: 4px 9px; font-weight: 600; border-radius: 6px;  background: '
               '#10b981; border: none; color: #ffffff; }QPushButton:hover { background: #059669; '
               '}QPushButton:pressed { background: #047857; }QPushButton:disabled { background: '
               '#f0f2f5; color: #b0b8cc; border: 1.5px solid #e8eaef; }',
 '_discard_btn': 'QPushButton { padding: 4px 9px; font-weight: 600; border-radius: 6px;  '
                 'background: #ffffff; border: 1.5px solid #fca5a5; color: #ef4444; '
                 '}QPushButton:hover { background: #fef2f2; border-color: #ef4444; '
                 '}QPushButton:pressed { background: #fee2e2; }QPushButton:disabled { background: '
                 '#f8f9fc; color: #b0b8cc; border-color: #e8eaef; }',
 '_page_prev_btn': 'QPushButton { font-size: 14px; font-weight: 700; border-radius: 8px;  color: '
                   '#2f3b56; border: 1px solid #ffffff; border-bottom: 2px solid #d5dceb;  '
                   'padding: 0px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, '
                   'stop:1 #e9eff9); }QPushButton:hover { color:#4361ee; '
                   'border-bottom-color:#4361ee; background:#eef3ff; }QPushButton:pressed { '
                   'background:#dde4ff; }',
 '_page_next_btn': 'QPushButton { font-size: 14px; font-weight: 700; border-radius: 8px;  color: '
                   '#2f3b56; border: 1px solid #ffffff; border-bottom: 2px solid #d5dceb;  '
                   'padding: 0px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, '
                   'stop:1 #e9eff9); }QPushButton:hover { color:#4361ee; '
                   'border-bottom-color:#4361ee; background:#eef3ff; }QPushButton:pressed { '
                   'background:#dde4ff; }',
 '_page_go_btn': 'QPushButton { font-weight: 600; border-radius: 6px;  background: #4361ee; '
                 'border: none; color: #ffffff; }QPushButton:hover { background: #3451d1; '
                 '}QPushButton:pressed { background: #2c44b8; }'}
