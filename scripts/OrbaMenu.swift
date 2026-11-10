import AppKit
import CoreBluetooth
import CoreMIDI
import Foundation

final class OrbaMenuApp: NSObject, NSApplicationDelegate, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var item: NSStatusItem!
    private var stateItem: NSMenuItem!
    private var backend: Process?
    private var outputPipe: Pipe?
    private var inputPipe: Pipe?
    private var pendingOutput = ""
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var scanTimeout: Timer?
    private var reconnectTimer: Timer?
    private var activationPending = false
    private var isScanning = false
    private var midiClient = MIDIClientRef()
    private var midiSource = MIDIEndpointRef()
    private let midiService = CBUUID(string: "03B80E5A-EDE8-4B33-A751-6CE34EC4C700")
    private let midiCharacteristic = CBUUID(string: "7772E5DB-3868-4112-A1A9-F2669D106BF3")
    private let project = "/Users/zehiu/Documents/dev/Orba"
    private let python = "/Users/zehiu/Documents/dev/Orba/.venv/bin/python"
    private let logURL = URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/ORBA Controller.log")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "◉ Orba"
        let menu = NSMenu()
        stateItem = NSMenuItem(title: "Iniciando BLE MIDI…", action: nil, keyEquivalent: "")
        stateItem.isEnabled = false
        menu.addItem(stateItem)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Reconectar ahora", action: #selector(reconnect), keyEquivalent: "r"))
        menu.addItem(NSMenuItem(title: "Abrir registro", action: #selector(openLog), keyEquivalent: "l"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Salir de ORBA Controller", action: #selector(quit), keyEquivalent: "q"))
        for menuItem in menu.items { menuItem.target = self }
        item.menu = menu

        createVirtualMidiSource()
        appendLog("Inicializando CoreBluetooth; autorización=\(CBCentralManager.authorization.rawValue)")
        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionShowPowerAlertKey: false]
        )
        appendLog("CBCentralManager creado")
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            self?.scanForOrbaIfNeeded()
        }
        startBackend()
    }

    private func createVirtualMidiSource() {
        let clientStatus = MIDIClientCreate("ORBA Controller" as CFString, nil, nil, &midiClient)
        guard clientStatus == noErr else {
            appendLog("No se pudo crear cliente CoreMIDI: OSStatus \(clientStatus)")
            return
        }
        let sourceStatus = MIDISourceCreate(midiClient, "ORBA Controller BLE MIDI" as CFString, &midiSource)
        if sourceStatus == noErr {
            appendLog("Entrada MIDI virtual creada para el Orba BLE")
        } else {
            appendLog("No se pudo crear entrada MIDI virtual: OSStatus \(sourceStatus)")
        }
    }

    private func isPhysicalOrbaMidiOnline() -> Bool {
        let count = MIDIGetNumberOfSources()
        guard count > 0 else { return false }
        for index in 0..<count {
            let source = MIDIGetSource(index)
            guard source != 0 else { continue }
            var unmanagedName: Unmanaged<CFString>?
            guard MIDIObjectGetStringProperty(source, kMIDIPropertyName, &unmanagedName) == noErr,
                  let unmanagedName else { continue }
            let name = unmanagedName.takeRetainedValue() as String
            guard name.localizedCaseInsensitiveContains("orba") || name.localizedCaseInsensitiveContains("artiphon") else { continue }
            guard !name.localizedCaseInsensitiveContains("orba controller") else { continue }
            var offline: Int32 = 0
            if MIDIObjectGetIntegerProperty(source, kMIDIPropertyOffline, &offline) == noErr && offline == 0 {
                return true
            }
        }
        return false
    }

    private func scanForOrbaIfNeeded() {
        guard central.state == .poweredOn, peripheral == nil, !activationPending, !isScanning else { return }
        if isPhysicalOrbaMidiOnline() {
            stateItem.title = "Conectado por BLE MIDI"
            item.button?.title = "◉ Orba ✓"
            return
        }
        stateItem.title = "Buscando Orba para reconectar…"
        item.button?.title = "◉ Orba …"
        isScanning = true
        central.scanForPeripherals(withServices: [midiService], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        scanTimeout?.invalidate()
        scanTimeout = Timer.scheduledTimer(withTimeInterval: 12, repeats: false) { [weak self] _ in
            guard let self, self.peripheral == nil else { return }
            self.central.stopScan()
            self.isScanning = false
            self.appendLog("No se detectó Orba BLE; nuevo intento en 3 s")
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            appendLog("Bluetooth listo; buscando Orba MIDI BLE")
            scanForOrbaIfNeeded()
        case .poweredOff:
            central.stopScan()
            isScanning = false
            stateItem.title = "Activa Bluetooth en el Mac; esperando Orba…"
            item.button?.title = "◉ Orba …"
        case .unauthorized:
            stateItem.title = "Permite Bluetooth para ORBA Controller"
            appendLog("Acceso Bluetooth denegado para ORBA Controller")
        case .unsupported:
            stateItem.title = "Este Mac no ofrece Bluetooth LE"
        default:
            stateItem.title = "Esperando Bluetooth del Mac…"
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let name = peripheral.name ?? advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? ""
        guard name.localizedCaseInsensitiveContains("orba") || name.localizedCaseInsensitiveContains("artiphon") else { return }
        self.peripheral = peripheral
        activationPending = true
        isScanning = false
        scanTimeout?.invalidate()
        central.stopScan()
        stateItem.title = "Orba detectado — conectando BLE…"
        appendLog("Orba BLE detectado: \(name); conectando")
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        appendLog("Enlace BLE establecido con \(peripheral.name ?? "Orba"); buscando servicio MIDI")
        peripheral.delegate = self
        peripheral.discoverServices([midiService])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == midiService }) else {
            appendLog("Orba no anunció el servicio MIDI BLE: \(error?.localizedDescription ?? "servicio ausente")")
            activationPending = false
            self.peripheral = nil
            central.cancelPeripheralConnection(peripheral)
            return
        }
        peripheral.discoverCharacteristics([midiCharacteristic], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil, let characteristic = service.characteristics?.first(where: { $0.uuid == midiCharacteristic }) else {
            appendLog("Orba no anunció la característica MIDI BLE: \(error?.localizedDescription ?? "característica ausente")")
            activationPending = false
            self.peripheral = nil
            central.cancelPeripheralConnection(peripheral)
            return
        }
        appendLog("Característica MIDI BLE encontrada; suscribiendo notificaciones")
        peripheral.setNotifyValue(true, for: characteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard characteristic.uuid == midiCharacteristic else { return }
        guard error == nil, characteristic.isNotifying else {
            appendLog("No se pudo activar notificación MIDI BLE: \(error?.localizedDescription ?? "notificación desactivada")")
            activationPending = false
            stateItem.title = "No se pudo activar MIDI BLE"
            return
        }
        let status = MIDIBluetoothDriverActivateAllConnections()
        appendLog("Notificaciones BLE activas; CoreMIDI OSStatus \(status); puente virtual listo")
        activationPending = false
        stateItem.title = "Orba conectado — recibiendo MIDI BLE"
        item.button?.title = "◉ Orba ✓"
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard characteristic.uuid == midiCharacteristic, error == nil, let data = characteristic.value else { return }
        for message in BLEMIDIDecoder.decode(data) {
            publishMIDI(message)
        }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        self.peripheral = nil
        activationPending = false
        isScanning = false
        appendLog("BLE Orba desconectado; la app buscará al volver a encenderse")
        stateItem.title = "Orba apagado — esperando para reconectar…"
        item.button?.title = "◉ Orba …"
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.scanForOrbaIfNeeded() }
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        self.peripheral = nil
        activationPending = false
        isScanning = false
        appendLog("Falló conexión BLE Orba: \(error?.localizedDescription ?? "error desconocido")")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { self.scanForOrbaIfNeeded() }
    }

    private func publishMIDI(_ bytes: [UInt8]) {
        guard midiSource != 0, !bytes.isEmpty else { return }
        let capacity = MemoryLayout<MIDIPacketList>.size + bytes.count + 64
        let raw = UnsafeMutableRawPointer.allocate(byteCount: capacity, alignment: MemoryLayout<MIDIPacketList>.alignment)
        defer { raw.deallocate() }
        let packetList = raw.bindMemory(to: MIDIPacketList.self, capacity: 1)
        let firstPacket = MIDIPacketListInit(packetList)
        bytes.withUnsafeBufferPointer { buffer in
            _ = MIDIPacketListAdd(packetList, capacity, firstPacket, 0, buffer.count, buffer.baseAddress!)
        }
        let status = MIDIReceived(midiSource, UnsafePointer(packetList))
        if status != noErr { appendLog("MIDIReceived falló: OSStatus \(status)") }
    }

    private func startBackend() {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        task.arguments = ["-B", "-u", "-m", "orba_controller.main", "--gesture-monitor", "--execute-actions", "--duration", "31536000"]
        task.currentDirectoryURL = URL(fileURLWithPath: project)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = "\(project)/src"
        task.environment = env
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        outputPipe = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        task.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.backend === task else { return }
                self.stateItem.title = "Reabriendo el controlador MIDI…"
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.startBackend() }
            }
        }
        do {
            try task.run()
            backend = task
        } catch {
            stateItem.title = "No se pudo iniciar: \(error.localizedDescription)"
        }
    }

    private func consume(_ data: Data) {
        pendingOutput += String(decoding: data, as: UTF8.self)
        let lines = pendingOutput.components(separatedBy: .newlines)
        pendingOutput = lines.last ?? ""
        for line in lines.dropLast() {
            appendLog(line)
            if line.contains("MIDI input connected:") {
                if line.contains("ORBA Controller BLE MIDI") {
                    stateItem.title = peripheral == nil ? "App lista — buscando Orba BLE…" : "Orba conectado — recibiendo BLE MIDI"
                } else if peripheral == nil {
                    stateItem.title = "Conectado por BLE MIDI"
                }
            } else if line.contains("MIDI input disconnected:") || line.contains("MIDI reconnect failed:") {
                if peripheral == nil {
                    stateItem.title = "Esperando Orba BLE…"
                    item.button?.title = "◉ Orba …"
                }
            } else if line.contains("Unable to enable application actions") {
                stateItem.title = "Revisa permisos de Automatización"
            }
        }
    }

    private func appendLog(_ line: String) {
        let record = "\(ISO8601DateFormatter().string(from: Date())) \(line)\\n"
        let data = Data(record.utf8)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: logURL) {
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
            try? handle.close()
        }
    }

    @objc private func reconnect() {
        stateItem.title = "Buscando Orba BLE…"
        if let task = backend, task.isRunning { task.terminate() }
        backend = nil
        if let peripheral { central.cancelPeripheralConnection(peripheral) }
        self.peripheral = nil
        activationPending = false
        isScanning = false
        central.stopScan()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.scanForOrbaIfNeeded() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.startBackend() }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(logURL)
    }

    @objc private func quit() {
        reconnectTimer?.invalidate()
        scanTimeout?.invalidate()
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        if let task = backend, task.isRunning { task.terminate() }
        if let peripheral { central.cancelPeripheralConnection(peripheral) }
        NSApp.terminate(nil)
    }
}

private enum BLEMIDIDecoder {
    static func decode(_ data: Data) -> [[UInt8]] {
        let bytes = Array(data)
        guard bytes.count >= 3 else { return [] }
        var messages: [[UInt8]] = []
        var index = 0
        while index < bytes.count {
            while index < bytes.count && (bytes[index] & 0xC0) != 0x80 { index += 1 }
            guard index < bytes.count else { break }
            index += 1 // BLE-MIDI timestamp high
            guard index < bytes.count else { break }
            index += 1 // BLE-MIDI timestamp low
            while index < bytes.count {
                guard bytes[index] & 0x80 != 0 else { index += 1; continue }
                let status = bytes[index]
                index += 1
                if status >= 0xF8 {
                    messages.append([status])
                    continue
                }
                let length: Int
                switch status {
                case 0x80...0xBF, 0xE0...0xEF: length = 2
                case 0xC0...0xDF: length = 1
                default:
                    if status == 0xF0 {
                        while index < bytes.count && bytes[index] < 0x80 { index += 1 }
                    }
                    continue
                }
                var midi = [status]
                while midi.count <= length && index < bytes.count && bytes[index] < 0x80 {
                    midi.append(bytes[index])
                    index += 1
                }
                if midi.count == length + 1 {
                    if status & 0xF0 == 0x90 && midi.count == 3 && midi[2] == 0 {
                        midi[0] = 0x80 | (status & 0x0F)
                    }
                    messages.append(midi)
                }
                if index < bytes.count && bytes[index] >= 0x80 && (bytes[index] & 0xC0) != 0x80 {
                    // A realtime or system status may follow without a packet header.
                    continue
                }
                if index < bytes.count && bytes[index] >= 0x80 {
                    index += 1 // timestamp before the next MIDI message
                }
            }
        }
        return messages
    }
}

let app = NSApplication.shared
let delegate = OrbaMenuApp()
app.delegate = delegate
app.run()
