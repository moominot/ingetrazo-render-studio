"""For tools/panel_shots.py: one picture of each page of the panel."""


def shots(panel, grab):
    for index in range(panel.tabs.count()):
        panel.tabs.setCurrentIndex(index)
        grab()
