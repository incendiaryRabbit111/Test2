# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenuBar, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QStackedWidget,
    QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1280, 800)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.mainLayout = QVBoxLayout(self.centralwidget)
        self.mainLayout.setObjectName(u"mainLayout")
        self.topBar = QWidget(self.centralwidget)
        self.topBar.setObjectName(u"topBar")
        self.topLayout = QHBoxLayout(self.topBar)
        self.topLayout.setSpacing(14)
        self.topLayout.setObjectName(u"topLayout")
        self.topLayout.setContentsMargins(20, 9, 20, 9)
        self.titleBox = QVBoxLayout()
        self.titleBox.setSpacing(1)
        self.titleBox.setObjectName(u"titleBox")
        self.labelTitle = QLabel(self.topBar)
        self.labelTitle.setObjectName(u"labelTitle")

        self.titleBox.addWidget(self.labelTitle)

        self.labelSubtitle = QLabel(self.topBar)
        self.labelSubtitle.setObjectName(u"labelSubtitle")

        self.titleBox.addWidget(self.labelSubtitle)


        self.topLayout.addLayout(self.titleBox)

        self.btnGuide = QPushButton(self.topBar)
        self.btnGuide.setObjectName(u"btnGuide")
        self.btnGuide.setMinimumSize(QSize(22, 22))
        self.btnGuide.setMaximumSize(QSize(22, 22))

        self.topLayout.addWidget(self.btnGuide)

        self.topSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.topLayout.addItem(self.topSpacer)

        self.labelMode = QLabel(self.topBar)
        self.labelMode.setObjectName(u"labelMode")

        self.topLayout.addWidget(self.labelMode)

        self.comboProvider = QComboBox(self.topBar)
        self.comboProvider.setObjectName(u"comboProvider")
        self.comboProvider.setMinimumSize(QSize(250, 0))

        self.topLayout.addWidget(self.comboProvider)

        self.btnApiSettings = QPushButton(self.topBar)
        self.btnApiSettings.setObjectName(u"btnApiSettings")

        self.topLayout.addWidget(self.btnApiSettings)

        self.labelModeValue = QLabel(self.topBar)
        self.labelModeValue.setObjectName(u"labelModeValue")

        self.topLayout.addWidget(self.labelModeValue)

        self.btnMore = QPushButton(self.topBar)
        self.btnMore.setObjectName(u"btnMore")
        self.btnMore.setMinimumSize(QSize(28, 28))
        self.btnMore.setMaximumSize(QSize(28, 28))

        self.topLayout.addWidget(self.btnMore)


        self.mainLayout.addWidget(self.topBar)

        self.splitter = QSplitter(self.centralwidget)
        self.splitter.setObjectName(u"splitter")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(1)
        sizePolicy.setHeightForWidth(self.splitter.sizePolicy().hasHeightForWidth())
        self.splitter.setSizePolicy(sizePolicy)
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.leftPane = QWidget(self.splitter)
        self.leftPane.setObjectName(u"leftPane")
        self.leftPane.setMinimumSize(QSize(210, 0))
        self.leftPane.setMaximumSize(QSize(280, 16777215))
        self.leftLayout = QVBoxLayout(self.leftPane)
        self.leftLayout.setSpacing(8)
        self.leftLayout.setObjectName(u"leftLayout")
        self.leftLayout.setContentsMargins(12, 12, 12, 12)
        self.btnNew = QPushButton(self.leftPane)
        self.btnNew.setObjectName(u"btnNew")

        self.leftLayout.addWidget(self.btnNew)

        self.labelListTitle = QLabel(self.leftPane)
        self.labelListTitle.setObjectName(u"labelListTitle")

        self.leftLayout.addWidget(self.labelListTitle)

        self.listStack = QStackedWidget(self.leftPane)
        self.listStack.setObjectName(u"listStack")
        self.listPage = QWidget()
        self.listPage.setObjectName(u"listPage")
        self.listPageLayout = QVBoxLayout(self.listPage)
        self.listPageLayout.setObjectName(u"listPageLayout")
        self.listPageLayout.setContentsMargins(0, 0, 0, 0)
        self.sessionList = QListWidget(self.listPage)
        self.sessionList.setObjectName(u"sessionList")

        self.listPageLayout.addWidget(self.sessionList)

        self.listStack.addWidget(self.listPage)
        self.emptyPage = QWidget()
        self.emptyPage.setObjectName(u"emptyPage")
        self.emptyPageLayout = QVBoxLayout(self.emptyPage)
        self.emptyPageLayout.setObjectName(u"emptyPageLayout")
        self.emptyTop = QSpacerItem(20, 80, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.emptyPageLayout.addItem(self.emptyTop)

        self.labelEmptyList = QLabel(self.emptyPage)
        self.labelEmptyList.setObjectName(u"labelEmptyList")
        self.labelEmptyList.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.emptyPageLayout.addWidget(self.labelEmptyList)

        self.emptyBottom = QSpacerItem(20, 120, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.emptyPageLayout.addItem(self.emptyBottom)

        self.listStack.addWidget(self.emptyPage)

        self.leftLayout.addWidget(self.listStack)

        self.labelCount = QLabel(self.leftPane)
        self.labelCount.setObjectName(u"labelCount")

        self.leftLayout.addWidget(self.labelCount)

        self.btnBatchImport = QPushButton(self.leftPane)
        self.btnBatchImport.setObjectName(u"btnBatchImport")

        self.leftLayout.addWidget(self.btnBatchImport)

        self.splitter.addWidget(self.leftPane)
        self.rightStack = QStackedWidget(self.splitter)
        self.rightStack.setObjectName(u"rightStack")
        self.inputPage = QWidget()
        self.inputPage.setObjectName(u"inputPage")
        self.inputLayout = QVBoxLayout(self.inputPage)
        self.inputLayout.setSpacing(10)
        self.inputLayout.setObjectName(u"inputLayout")
        self.inputLayout.setContentsMargins(18, 16, 18, 16)
        self.labelInput = QLabel(self.inputPage)
        self.labelInput.setObjectName(u"labelInput")

        self.inputLayout.addWidget(self.labelInput)

        self.inputText = QPlainTextEdit(self.inputPage)
        self.inputText.setObjectName(u"inputText")

        self.inputLayout.addWidget(self.inputText)

        self.timeLayout = QHBoxLayout()
        self.timeLayout.setObjectName(u"timeLayout")
        self.labelTime = QLabel(self.inputPage)
        self.labelTime.setObjectName(u"labelTime")

        self.timeLayout.addWidget(self.labelTime)

        self.timeInput = QLineEdit(self.inputPage)
        self.timeInput.setObjectName(u"timeInput")
        self.timeInput.setMaximumSize(QSize(240, 16777215))

        self.timeLayout.addWidget(self.timeInput)

        self.timeSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.timeLayout.addItem(self.timeSpacer)


        self.inputLayout.addLayout(self.timeLayout)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.btnClear = QPushButton(self.inputPage)
        self.btnClear.setObjectName(u"btnClear")

        self.buttonLayout.addWidget(self.btnClear)

        self.btnSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.buttonLayout.addItem(self.btnSpacer)


        self.inputLayout.addLayout(self.buttonLayout)

        self.rightStack.addWidget(self.inputPage)
        self.resultPage = QWidget()
        self.resultPage.setObjectName(u"resultPage")
        self.resultLayout = QVBoxLayout(self.resultPage)
        self.resultLayout.setSpacing(10)
        self.resultLayout.setObjectName(u"resultLayout")
        self.resultLayout.setContentsMargins(18, 14, 18, 14)
        self.tabResults = QTabWidget(self.resultPage)
        self.tabResults.setObjectName(u"tabResults")
        self.tabMetrics = QWidget()
        self.tabMetrics.setObjectName(u"tabMetrics")
        self.metricsLayout = QVBoxLayout(self.tabMetrics)
        self.metricsLayout.setObjectName(u"metricsLayout")
        self.tblMetrics = QTableWidget(self.tabMetrics)
        self.tblMetrics.setObjectName(u"tblMetrics")

        self.metricsLayout.addWidget(self.tblMetrics)

        self.tabResults.addTab(self.tabMetrics, "")
        self.tabEvaluations = QWidget()
        self.tabEvaluations.setObjectName(u"tabEvaluations")
        self.evaluationsLayout = QVBoxLayout(self.tabEvaluations)
        self.evaluationsLayout.setObjectName(u"evaluationsLayout")
        self.tblEvaluations = QTableWidget(self.tabEvaluations)
        self.tblEvaluations.setObjectName(u"tblEvaluations")

        self.evaluationsLayout.addWidget(self.tblEvaluations)

        self.tabResults.addTab(self.tabEvaluations, "")
        self.tabReport = QWidget()
        self.tabReport.setObjectName(u"tabReport")
        self.reportLayout = QVBoxLayout(self.tabReport)
        self.reportLayout.setObjectName(u"reportLayout")
        self.txtReport = QPlainTextEdit(self.tabReport)
        self.txtReport.setObjectName(u"txtReport")
        self.txtReport.setReadOnly(True)

        self.reportLayout.addWidget(self.txtReport)

        self.tabResults.addTab(self.tabReport, "")
        self.tabTrend = QWidget()
        self.tabTrend.setObjectName(u"tabTrend")
        self.trendLayout = QVBoxLayout(self.tabTrend)
        self.trendLayout.setObjectName(u"trendLayout")
        self.trendHolder = QWidget(self.tabTrend)
        self.trendHolder.setObjectName(u"trendHolder")

        self.trendLayout.addWidget(self.trendHolder)

        self.tabResults.addTab(self.tabTrend, "")

        self.resultLayout.addWidget(self.tabResults)

        self.rightStack.addWidget(self.resultPage)
        self.splitter.addWidget(self.rightStack)

        self.mainLayout.addWidget(self.splitter)

        self.bottomLayout = QHBoxLayout()
        self.bottomLayout.setObjectName(u"bottomLayout")
        self.labelSummary = QLabel(self.centralwidget)
        self.labelSummary.setObjectName(u"labelSummary")

        self.bottomLayout.addWidget(self.labelSummary)

        self.pillBar = QWidget(self.centralwidget)
        self.pillBar.setObjectName(u"pillBar")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.pillBar.sizePolicy().hasHeightForWidth())
        self.pillBar.setSizePolicy(sizePolicy1)
        self.pillLayout = QHBoxLayout(self.pillBar)
        self.pillLayout.setSpacing(6)
        self.pillLayout.setObjectName(u"pillLayout")
        self.pillLayout.setContentsMargins(0, 0, 0, 0)

        self.bottomLayout.addWidget(self.pillBar)

        self.bottomSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.bottomLayout.addItem(self.bottomSpacer)

        self.btnAnalyze = QPushButton(self.centralwidget)
        self.btnAnalyze.setObjectName(u"btnAnalyze")

        self.bottomLayout.addWidget(self.btnAnalyze)

        self.btnExport = QPushButton(self.centralwidget)
        self.btnExport.setObjectName(u"btnExport")
        self.btnExport.setEnabled(False)

        self.bottomLayout.addWidget(self.btnExport)


        self.mainLayout.addLayout(self.bottomLayout)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        self.tabResults.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u7279\u5f81\u5fae\u751f\u7269\u5206\u6790\u5de5\u5177 (Demo)", None))
        self.labelTitle.setText(QCoreApplication.translate("MainWindow", u"\u7279\u5f81\u5fae\u751f\u7269\u5206\u6790\u5de5\u5177", None))
        self.labelTitle.setStyleSheet(QCoreApplication.translate("MainWindow", u"font-size:16px;font-weight:600;color:#1C262D;", None))
        self.labelSubtitle.setText(QCoreApplication.translate("MainWindow", u"\u5fae\u751f\u7269\u955c\u68c0\u5206\u6790 \u00b7 \u672c\u5730\u77e5\u8bc6\u5e93", None))
        self.labelSubtitle.setStyleSheet(QCoreApplication.translate("MainWindow", u"font-size:11px;color:#8C9B93;", None))
        self.btnGuide.setText(QCoreApplication.translate("MainWindow", u"?", None))
#if QT_CONFIG(tooltip)
        self.btnGuide.setToolTip(QCoreApplication.translate("MainWindow", u"\u89c2\u770b\u4f7f\u7528\u6559\u7a0b", None))
#endif // QT_CONFIG(tooltip)
        self.labelMode.setText(QCoreApplication.translate("MainWindow", u"\u4f7f\u7528\u6a21\u578b", None))
        self.labelMode.setStyleSheet(QCoreApplication.translate("MainWindow", u"color:#5C6C64;", None))
        self.btnApiSettings.setText(QCoreApplication.translate("MainWindow", u"API \u8bbe\u7f6e", None))
        self.labelModeValue.setText(QCoreApplication.translate("MainWindow", u"-", None))
        self.labelModeValue.setStyleSheet(QCoreApplication.translate("MainWindow", u"color:#1a7f37;font-weight:600;", None))
        self.btnMore.setText(QCoreApplication.translate("MainWindow", u"\u2261", None))
#if QT_CONFIG(tooltip)
        self.btnMore.setToolTip(QCoreApplication.translate("MainWindow", u"\u66f4\u591a\u8bbe\u7f6e", None))
#endif // QT_CONFIG(tooltip)
        self.btnNew.setText(QCoreApplication.translate("MainWindow", u"\uff0b \u65b0\u5efa\u5206\u6790", None))
        self.labelListTitle.setText(QCoreApplication.translate("MainWindow", u"\u4f1a\u8bdd\u8bb0\u5f55", None))
        self.labelListTitle.setStyleSheet(QCoreApplication.translate("MainWindow", u"color:#666;", None))
        self.labelEmptyList.setText(QCoreApplication.translate("MainWindow", u"\u8fd8\u6ca1\u6709\u5206\u6790\u8bb0\u5f55\n"
"\n"
"\u70b9\u300c\uff0b \u65b0\u5efa\u5206\u6790\u300d\u5f00\u59cb", None))
        self.labelEmptyList.setStyleSheet(QCoreApplication.translate("MainWindow", u"color:#9AA9A1;font-size:11px;line-height:150%;", None))
        self.labelCount.setText(QCoreApplication.translate("MainWindow", u"\u5171 0 \u6761", None))
        self.labelCount.setStyleSheet(QCoreApplication.translate("MainWindow", u"color:#888;font-size:11px;", None))
        self.btnBatchImport.setText(QCoreApplication.translate("MainWindow", u"\u6279\u91cf\u5bfc\u5165", None))
        self.labelInput.setText(QCoreApplication.translate("MainWindow", u"\u7c98\u8d34\u4eea\u5668\u8f93\u51fa\u6587\u672c", None))
        self.inputText.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u5728\u6b64\u7c98\u8d34\u4eea\u5668\u8f93\u51fa\u6587\u672c\uff0c\u4f8b\u5982\uff1a\n"
"\n"
"\u5185\u7ba1\u866b: 0.346, \u5323\u58f3\u866b: 0.115, \u626d\u66f2\u7ba1\u53f6\u866b: 0.403, \u8868\u58f3\u866b: 1.440 \u2026\n"
"\u6d53\u5ea6\u5355\u4f4d(10^6 \u4e2a/L)\n"
"\n"
"\uff08\u53ea\u5199\"\u7269\u79cd: \u6d53\u5ea6\"\u4e5f\u80fd\u8bc6\u522b\uff09", None))
        self.labelTime.setText(QCoreApplication.translate("MainWindow", u"\u91c7\u6837\u65f6\u95f4\uff1a", None))
        self.timeInput.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u4f8b 2026-10-10 09:00\uff08\u53ef\u7559\u7a7a\uff09", None))
        self.btnClear.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u7a7a", None))
        self.tabResults.setTabText(self.tabResults.indexOf(self.tabMetrics), QCoreApplication.translate("MainWindow", u"\u2460 \u8ba1\u7b97\u6307\u6807", None))
        self.tabResults.setTabText(self.tabResults.indexOf(self.tabEvaluations), QCoreApplication.translate("MainWindow", u"\u2461 \u7269\u79cd\u8bc4\u4ef7", None))
        self.tabResults.setTabText(self.tabResults.indexOf(self.tabReport), QCoreApplication.translate("MainWindow", u"\u2462 AI \u5206\u6790\u62a5\u544a", None))
        self.tabResults.setTabText(self.tabResults.indexOf(self.tabTrend), QCoreApplication.translate("MainWindow", u"\u2463 \u8d8b\u52bf\u5bf9\u6bd4", None))
        self.labelSummary.setText(QCoreApplication.translate("MainWindow", u"\u5c31\u7eea", None))
        self.btnAnalyze.setText(QCoreApplication.translate("MainWindow", u"\u5206\u6790", None))
        self.btnExport.setText(QCoreApplication.translate("MainWindow", u"\u5bfc\u51fa\u5f53\u524d\u8bb0\u5f55", None))
    # retranslateUi

