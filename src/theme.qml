import QtQuick
import QtQuick.Controls
import "theme_config.js" as Config

Item {
    id: root
    width: Config.previewMode ? Config.screenWidth : Config.layout.imageWidth
    height: Config.previewMode ? Config.screenHeight : Config.layout.imageHeight

    Image {
        anchors.fill: parent
        source: Config.wallpaperPath
        fillMode: Image.PreserveAspectCrop
        visible: Config.previewMode
    }

    Image {
        width: Config.layout.imageWidth
        height: Config.layout.imageHeight
        anchors.horizontalCenter: parent.horizontalCenter
        y: Config.previewMode ? root.height / 2 + Config.layout.panelTop - Config.layout.padding : 0
        source: Config.bgPath
    }

    Item {
        id: nexusWindow
        width: 1200
        height: 800
        x: (root.width - Config.layout.panelWidth) / 2
        y: Config.previewMode ? root.height / 2 + Config.layout.panelTop : Config.layout.padding
        scale: Config.layout.scale
        transformOrigin: Item.TopLeft

        Text {
            anchors.top: parent.top
            anchors.topMargin: 30
            anchors.left: parent.left
            anchors.leftMargin: 30
            text: "Select Operating System"
            color: Config.scheme.text || "#dce8e6"
            font.pixelSize: 28
            font.bold: true
        }
        
        Rectangle {
            x: 20
            y: 90
            width: 1160
            height: 620
            radius: 12
            color: Config.scheme.surfaceContainerLow || "#0e1514"
            opacity: Config.layersTransparency || 0.4
        }
        
        Row {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 30
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 20
            
            Repeater {
                model: [
                    { key: "↑/↓", action: "Navigate" },
                    { key: "Enter", action: "Boot" },
                    { key: "E", action: "Edit" },
                    { key: "C", action: "Command" }
                ]
                
                Rectangle {
                    width: hintRow.width + 30
                    height: 36
                    radius: 18 
                    color: Qt.alpha(Config.scheme.primaryContainer || "#255b58", Config.layersTransparency || 0.4)
                    
                    Row {
                        id: hintRow
                        anchors.centerIn: parent
                        spacing: 8
                        
                        Rectangle {
                            width: keyText.width + 16
                            height: 24
                            radius: 6
                            color: Qt.alpha(Config.scheme.primary || "#9bd0cc", Config.layersTransparency || 0.4)
                            anchors.verticalCenter: parent.verticalCenter
                            
                            Text {
                                id: keyText
                                anchors.centerIn: parent
                                text: modelData.key
                                color: Config.scheme.onPrimary || "#0d4845"
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "sans-serif"
                            }
                        }
                        
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.action
                            color: Config.scheme.onPrimaryContainer || "#b8ede9"
                            font.pixelSize: 14
                            font.family: "sans-serif"
                            font.bold: true
                        }
                    }
                }
            }
        }
    }
    Column {
        x: (root.width - Config.layout.menuWidth) / 2
        y: root.height / 2 + Config.layout.menuTop
        width: Config.layout.menuWidth
        height: Config.layout.menuHeight
        clip: true
        spacing: typeof Config.itemSpacing !== 'undefined' ? Config.itemSpacing : 14
        visible: typeof Config.previewMode !== 'undefined' ? Config.previewMode : false

        Repeater {
            model: [
                { text: "Artix Linux", icon: "artix.png", selected: true },
                { text: "Advanced options for Artix Linux", icon: "gnu-linux.png", selected: false },
                { text: "Windows 11", icon: "windows11.png", selected: false },
                { text: "UEFI Firmware Settings", icon: "efi.png", selected: false }
            ]

            Rectangle {
                width: parent.width
                height: Config.itemHeight + 2 * Config.itemPadding
                radius: 12
                color: Qt.alpha(modelData.selected ? (Config.scheme.surfaceContainerHighest || "#1d2827") : (Config.scheme.surfaceContainerHigh || "#192120"), Config.layersTransparency || 0.4)

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    spacing: 10

                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        source: typeof Config.previewMode !== 'undefined' && Config.previewMode ? Qt.resolvedUrl("../theme/icons/" + modelData.icon) : ""
                        width: 32
                        height: 32
                        fillMode: Image.PreserveAspectFit
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.text
                        color: modelData.selected ? (Config.scheme.text || "#dce8e6") : (Config.scheme.textDark || "#a2adac")
                        font.pixelSize: 22
                        font.family: "Google Sans Flex"
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height / 2 + Config.layout.barTop
        width: Config.layout.menuWidth
        height: Config.layout.barHeight
        radius: height / 2
        color: Config.scheme.surfaceContainerHigh || "#192120"
        visible: Config.previewMode

        Rectangle {
            width: parent.width * 0.65
            height: parent.height
            radius: height / 2
            color: Config.scheme.primary || "#9bd0cc"
        }
    }
}
