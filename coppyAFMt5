import MetaTrader5 as mt5
import time
import os
import json
from datetime import datetime
from typing import Dict, Tuple

# Configuración inicial
os.system('cls')
os.system('title CopyTrading ULTIMATE')
VERSION = "3.1"
COPY_MAGIC = 9999
MAX_RETRIES = 5
POLL_INTERVAL = 0.1
SYNC_INTERVAL = 5.0

class CopyTradingConfig:
    def __init__(self):
        self.config_file = "config.json"
        self.default_config = {
            "source_account": {
                "login": 0,
                "password": "password",
                "server": "server"
            },
            "target_account": {
                "login": 0,
                "password": "password",
                "server": "server"
            },
            "settings": {
                "volume_multiplier": 1.0,
                "enable_sl_tp_sync": True,
                "allow_no_sl_tp": True,
                "max_price_deviation": 2.0,
                "execution_timeout": 3.0
            }
        }
        
        self.load_config()
    
    def load_config(self):
        if not os.path.exists(self.config_file):
            self.create_default_config()
        
        with open(self.config_file, 'r') as f:
            config = json.load(f)
            
        self.source_account = config["source_account"]
        self.target_account = config["target_account"]
        self.settings = config["settings"]
        
        # Validación de config
        self.settings["volume_multiplier"] = max(0.01, float(self.settings["volume_multiplier"]))
        self.settings["max_price_deviation"] = max(0.1, float(self.settings["max_price_deviation"]))
        self.settings["execution_timeout"] = max(0.5, float(self.settings["execution_timeout"]))
        
    def create_default_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.default_config, f, indent=4)
        raise Exception("Archivo config.json creado. Configure las cuentas!")

class MT5ConnectionManager:
    _active_connections = {}
    
    def __init__(self, account):
        self.account = account
        self.login = account["login"]
    
    def __enter__(self):
        if self.login in MT5ConnectionManager._active_connections:
            return self
            
        if not mt5.initialize():
            raise ConnectionError(f"Error inicializando MT5: {mt5.last_error()}")
            
        authorized = mt5.login(
            self.account["login"],
            self.account["password"],
            self.account["server"]
        )
        
        if not authorized:
            mt5.shutdown()
            raise ConnectionError(f"Login fallido: {mt5.last_error()}")
            
        MT5ConnectionManager._active_connections[self.login] = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.login in MT5ConnectionManager._active_connections:
            mt5.shutdown()
            del MT5ConnectionManager._active_connections[self.login]

class TradeCopier:
    def __init__(self, config: CopyTradingConfig):
        self.config = config
        self.copied_positions: Dict[int, Tuple[int, float, float]] = {}
        self.last_sync = time.time()
        self.logger = self.setup_logger()
        
    def setup_logger(self):
        class AdvancedLogger:
            def __init__(self):
                self.log_file = "copytrading.log"
            
            def log(self, message: str, level: str = "INFO"):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                log_entry = f"[{timestamp}] [{level}] {message}"
                print(log_entry)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")
        
        return AdvancedLogger()
    
    def execute_with_retry(self, func, *args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.log(f"Intento {attempt+1} fallido: {str(e)}", "WARNING")
                time.sleep(0.5)
        raise Exception(f"Fallo después de {MAX_RETRIES} intentos")
    
    def copy_position(self, source_position) -> int:
        symbol = source_position.symbol
        volume = round(source_position.volume * self.config.settings["volume_multiplier"], 2)
        position_type = source_position.type
        price = self.get_current_price(symbol, position_type)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if position_type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": source_position.sl,
            "tp": source_position.tp,
            "deviation": int(self.config.settings["max_price_deviation"]),
            "magic": COPY_MAGIC,
            "comment": "COPYTRADE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK
        }
        
        with MT5ConnectionManager(self.config.target_account):
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise Exception(f"Error copiando operación: {result.comment}")
            
            # Verificar posición creada
            position = self.wait_for_position(symbol)
            return position.ticket
    
    def modify_position(self, target_ticket: int, new_sl: float, new_tp: float):
        with MT5ConnectionManager(self.config.target_account):
            position = mt5.positions_get(ticket=target_ticket)
            if not position:
                raise Exception("Posición no encontrada")
            
            position = position[0]
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": target_ticket,
                "symbol": position.symbol,
                "sl": new_sl,
                "tp": new_tp
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise Exception(f"Error modificando SL/TP: {result.comment}")
    
    def get_current_price(self, symbol: str, position_type: int) -> float:
        tick = mt5.symbol_info_tick(symbol)
        return tick.ask if position_type == mt5.POSITION_TYPE_BUY else tick.bid
    
    def wait_for_position(self, symbol: str):
        start_time = time.time()
        while (time.time() - start_time) < self.config.settings["execution_timeout"]:
            positions = mt5.positions_get(symbol=symbol, magic=COPY_MAGIC)
            if positions:
                return positions[0]
            time.sleep(0.1)
        raise Exception("Tiempo de espera agotado para posición")
    
    def sync_positions(self):
        try:
            with MT5ConnectionManager(self.config.source_account):
                source_positions = {p.ticket: p for p in mt5.positions_get()}
            
            # Sincronizar nuevas posiciones
            new_positions = set(source_positions.keys()) - set(self.copied_positions.keys())
            for ticket in new_positions:
                position = source_positions[ticket]
                if self.config.settings["allow_no_sl_tp"] or (position.sl != 0 or position.tp != 0):
                    try:
                        copied_ticket = self.execute_with_retry(self.copy_position, position)
                        self.copied_positions[ticket] = (copied_ticket, position.sl, position.tp)
                        self.logger.log(f"Posición copiada: {ticket} -> {copied_ticket}")
                    except Exception as e:
                        self.logger.log(f"Error copiando posición {ticket}: {str(e)}", "ERROR")
            
            # Sincronizar cierres
            closed_positions = set(self.copied_positions.keys()) - set(source_positions.keys())
            for ticket in closed_positions:
                target_ticket = self.copied_positions[ticket][0]
                try:
                    self.execute_with_retry(self.close_position, target_ticket)
                    del self.copied_positions[ticket]
                    self.logger.log(f"Posición cerrada: {target_ticket}")
                except Exception as e:
                    self.logger.log(f"Error cerrando posición {target_ticket}: {str(e)}", "ERROR")
            
            # Sincronizar modificaciones SL/TP
            if self.config.settings["enable_sl_tp_sync"]:
                for src_ticket, (tgt_ticket, prev_sl, prev_tp) in self.copied_positions.items():
                    current_position = source_positions.get(src_ticket)
                    if current_position and (current_position.sl != prev_sl or current_position.tp != prev_tp):
                        try:
                            self.execute_with_retry(self.modify_position, tgt_ticket, current_position.sl, current_position.tp)
                            self.copied_positions[src_ticket] = (tgt_ticket, current_position.sl, current_position.tp)
                            self.logger.log(f"SL/TP actualizado: {tgt_ticket} ({prev_sl}/{prev_tp} -> {current_position.sl}/{current_position.tp})")
                        except Exception as e:
                            self.logger.log(f"Error actualizando SL/TP {tgt_ticket}: {str(e)}", "ERROR")
            
            self.last_sync = time.time()
            
        except Exception as e:
            self.logger.log(f"Error en sincronización: {str(e)}", "CRITICAL")
    
    def close_position(self, target_ticket: int):
        with MT5ConnectionManager(self.config.target_account):
            position = mt5.positions_get(ticket=target_ticket)
            if not position:
                return
                
            position = position[0]
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": target_ticket,
                "price": self.get_current_price(position.symbol, position.type),
                "deviation": int(self.config.settings["max_price_deviation"]),
                "comment": "CT_CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise Exception(f"Error cerrando posición: {result.comment}")
    
    def run(self):
        self.logger.log(f"Iniciando CopyTrading ULTIMATE v{VERSION}")
        while True:
            try:
                self.sync_positions()
                sleep_time = SYNC_INTERVAL - (time.time() - self.last_sync)
                time.sleep(max(0.1, sleep_time))
            except KeyboardInterrupt:
                self.logger.log("Deteniendo sistema...")
                break
            except Exception as e:
                self.logger.log(f"Error crítico: {str(e)}", "CRITICAL")
                time.sleep(5)

if __name__ == "__main__":
    try:
        config = CopyTradingConfig()
        copier = TradeCopier(config)
        copier.run()
    except Exception as e:
        print(f"Error inicial: {str(e)}")
        time.sleep(30)
