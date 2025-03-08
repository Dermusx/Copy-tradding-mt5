import MetaTrader5 as mt5
import json
import os
import time
import threading
from datetime import datetime
from queue import Queue
from typing import Dict, List, Optional
import psutil

class MT5ConnectionPool:
    _instance = None
    _connections = {}
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_connection(cls, account: Dict) -> bool:
        with cls._lock:
            key = f"{account['login']}@{account['server']}"
            if key in cls._connections:
                if time.time() - cls._connections[key]['last_used'] < 300:
                    return True
                else:
                    mt5.shutdown()
            
            try:
                if not mt5.initialize():
                    raise ConnectionError(f"Initialize failed: {mt5.last_error()}")
                
                authorized = mt5.login(
                    account['login'],
                    account['password'],
                    account['server']
                )
                
                if authorized:
                    cls._connections[key] = {
                        'handle': mt5,
                        'last_used': time.time()
                    }
                    return True
                return False
            except Exception as e:
                print(f"Connection error: {str(e)}")
                return False
    
    @classmethod
    def release_unused(cls):
        with cls._lock:
            current_time = time.time()
            to_delete = []
            for key, conn in cls._connections.items():
                if current_time - conn['last_used'] > 300:
                    mt5.shutdown()
                    to_delete.append(key)
            for key in to_delete:
                del cls._connections[key]

class AdvancedLogger:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.log_queue = Queue()
            cls._instance.running = True
            cls._instance.worker = threading.Thread(target=cls._instance._write_logs)
            cls._instance.worker.daemon = True
            cls._instance.worker.start()
        return cls._instance
    
    def log(self, message: str, level: str = "INFO", pair_id: str = "GLOBAL"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] [{pair_id}] {message}"
        self.log_queue.put(log_entry)
    
    def _write_logs(self):
        with open("multicopy.log", "a", encoding="utf-8") as f:
            while self.running or not self.log_queue.empty():
                try:
                    entry = self.log_queue.get(timeout=1)
                    print(entry)
                    f.write(entry + "\n")
                    self.log_queue.task_done()
                except:
                    pass
    
    def shutdown(self):
        self.running = False
        self.worker.join()

class CopyPairManager(threading.Thread):
    def __init__(self, pair_config: Dict, pair_id: str):
        super().__init__(daemon=True)
        self.pair_config = pair_config
        self.pair_id = pair_id
        self.logger = AdvancedLogger()
        self.running = True
        self.copied_positions: Dict[int, int] = {}
        self.last_sync = time.time()
        self.position_lock = threading.Lock()
        
    def run(self):
        self.logger.log(f"Iniciando manager para par {self.pair_id}", "INFO", self.pair_id)
        while self.running:
            try:
                self._sync_positions()
                time.sleep(self.pair_config['settings'].get('sync_interval', 0.3))
                MT5ConnectionPool.release_unused()
            except Exception as e:
                self.logger.log(f"Error crítico: {str(e)}", "CRITICAL", self.pair_id)
                time.sleep(5)
    
    def _sync_positions(self):
        # Obtener posiciones fuente
        source_positions = self._get_positions(self.pair_config['source'])
        if source_positions is None:
            return
        
        # Obtener posiciones destino
        target_positions = self._get_positions(self.pair_config['target'])
        
        with self.position_lock:
            self._process_new_positions(source_positions, target_positions)
            self._process_closed_positions(source_positions)
            self._process_modifications(source_positions, target_positions)
    
    def _get_positions(self, account: Dict) -> Optional[List[mt5.TradePosition]]:
        if not MT5ConnectionPool.get_connection(account):
            self.logger.log(f"Conexión fallida a {account['login']}", "ERROR", self.pair_id)
            return None
        
        try:
            positions = mt5.positions_get()
            return {pos.ticket: pos for pos in positions} if positions else {}
        except Exception as e:
            self.logger.log(f"Error obteniendo posiciones: {str(e)}", "ERROR", self.pair_id)
            return None
    
    def _process_new_positions(self, source: Dict, target: Dict):
        new_positions = set(source.keys()) - set(self.copied_positions.keys())
        for ticket in new_positions:
            self._copy_position(source[ticket], target)
    
    def _copy_position(self, position: mt5.TradePosition, target_positions: Dict):
        # Validaciones
        if not self._validate_position(position):
            return
        
        # Preparar orden
        request = self._prepare_order_request(position)
        
        # Enviar orden
        if MT5ConnectionPool.get_connection(self.pair_config['target']):
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                new_ticket = self._get_target_ticket(result, target_positions)
                if new_ticket:
                    with self.position_lock:
                        self.copied_positions[position.ticket] = new_ticket
                    self.logger.log(f"Posición copiada {position.ticket}->{new_ticket}", "SUCCESS", self.pair_id)
            else:
                self.logger.log(f"Error copiando posición: {result.comment}", "ERROR", self.pair_id)
    
    def _prepare_order_request(self, position: mt5.TradePosition) -> Dict:
        symbol_info = mt5.symbol_info(position.symbol)
        multiplier = self.pair_config['settings'].get('volume_multiplier', 1.0)
        price = mt5.symbol_info_tick(position.symbol).ask if position.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(position.symbol).bid
        
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": round(position.volume * multiplier, 2),
            "type": mt5.ORDER_TYPE_BUY if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": position.sl,
            "tp": position.tp,
            "deviation": self.pair_config['settings'].get('max_deviation_pips', 5),
            "magic": int(time.time()),
            "comment": f"COPY_{self.pair_id}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK
        }
    
    def _validate_position(self, position: mt5.TradePosition) -> bool:
        # Filtros y validaciones
        symbol_filter = self.pair_config['settings'].get('symbol_filter', [])
        if symbol_filter and position.symbol not in symbol_filter:
            return False
        
        if position.volume <= 0:
            return False
            
        return True
    
    def _process_closed_positions(self, source_positions: Dict):
        closed = set(self.copied_positions.keys()) - set(source_positions.keys())
        for ticket in closed:
            self._close_position(ticket)
    
    def _close_position(self, source_ticket: int):
        target_ticket = self.copied_positions.get(source_ticket)
        if target_ticket and MT5ConnectionPool.get_connection(self.pair_config['target']):
            position = mt5.positions_get(ticket=target_ticket)
            if position:
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": target_ticket,
                    "symbol": position[0].symbol,
                    "volume": position[0].volume,
                    "type": mt5.ORDER_TYPE_SELL if position[0].type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                    "price": mt5.symbol_info_tick(position[0].symbol).bid if position[0].type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(position[0].symbol).ask,
                    "deviation": self.pair_config['settings'].get('max_deviation_pips', 5),
                    "comment": f"CLOSE_{self.pair_id}"
                }
                result = mt5.order_send(close_request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    with self.position_lock:
                        del self.copied_positions[source_ticket]
                    self.logger.log(f"Posición cerrada {target_ticket}", "SUCCESS", self.pair_id)
    
    def _process_modifications(self, source: Dict, target: Dict):
        for src_ticket, tgt_ticket in self.copied_positions.items():
            src_pos = source.get(src_ticket)
            tgt_pos = target.get(tgt_ticket)
            
            if src_pos and tgt_pos:
                if src_pos.sl != tgt_pos.sl or src_pos.tp != tgt_pos.tp:
                    self._modify_position(tgt_ticket, src_pos.sl, src_pos.tp)
    
    def _modify_position(self, ticket: int, sl: float, tp: float):
        if MT5ConnectionPool.get_connection(self.pair_config['target']):
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": sl,
                "tp": tp
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.log(f"Modificado SL/TP {ticket}", "INFO", self.pair_id)
    
    def _get_target_ticket(self, result, target_positions: Dict) -> Optional[int]:
        time.sleep(0.2)
        new_positions = mt5.positions_get()
        if new_positions:
            for pos in new_positions:
                if pos.ticket not in target_positions:
                    return pos.ticket
        return None

class ResourceMonitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.logger = AdvancedLogger()
        self.running = True
    
    def run(self):
        while self.running:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            self.logger.log(f"Monitor: CPU={cpu}% MEM={mem}%", "DEBUG", "MONITOR")
            time.sleep(60)

class MultiCopyManager:
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.logger = AdvancedLogger()
        self.pair_managers = []
        self.resource_monitor = ResourceMonitor()
        
    def _load_config(self, file_path: str) -> Dict:
        with open(file_path, 'r') as f:
            config = json.load(f)
        return config
    
    def start(self):
        self.resource_monitor.start()
        
        for idx, pair in enumerate(self.config['copy_pairs']):
            manager = CopyPairManager(pair, f"PAIR_{idx+1}")
            manager.start()
            self.pair_managers.append(manager)
            time.sleep(0.5)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.log("Deteniendo todos los procesos...", "INFO", "GLOBAL")
            for manager in self.pair_managers:
                manager.running = False
            self.resource_monitor.running = False

if __name__ == "__main__":
    manager = MultiCopyManager()
    manager.start()
