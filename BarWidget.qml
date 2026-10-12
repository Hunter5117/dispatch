import QtQuick
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.samcapshaw.dispatch"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰎕"
    tooltipText: "Dispatch · News Reader"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton && root.bar)
        root.bar.run("omarchy-shell dispatch open")
    }
  }
}
