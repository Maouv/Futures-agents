Yang dihapus dari constructor:
Parameter: use_rl, rl_model_path, rl_norm_path (baris 64-66)
Assignment: self.use_rl = use_rl (baris 78)
Komentar + 2 state tracking vars: _last_trade_exit_time, _consecutive_losses (baris 83-85)
Seluruh RL engine init block (baris 87-102)
Methods yang dihapus seluruhnya:
_build_rl_state() (baris 106-160)
_calculate_consecutive_losses() (baris 161-172)
_calculate_time_since_last_trade() (baris 174-181)
_calculate_drawdown_pct() (baris 183-189)
Dari main loop — hapus:
Update state tracking setelah close position (baris 289-293): self._last_trade_exit_time, self._consecutive_losses
Kalkulasi candle_body_ratio dan distance_to_ob sebelum position = { (baris 396-401) — tapi cek dulu, karena keduanya masuk ke position dict, perlu tau apakah dipakai selain untuk RL fields
Dari position dict: key bos_choch, fvg_present, candle_body_ratio, distance_to_ob
Seluruh blok RL filter (baris 415-453)
Dari _close_position():
Seluruh section # Populate RL training fields sampai sebelum return TradeResult()
Dari return TradeResult(): semua field RL (bos_type, ob_size, distance_to_ob, fvg_present, candle_body_ratio, hour_of_day, consecutive_losses, time_since_last_trade, current_drawdown_pct)
Dari export_to_csv():
fieldnames list: hapus ob_size, distance_to_ob, bos_type, fvg_present, candle_body_ratio, hour_of_day, consecutive_losses, time_since_last_trade, current_drawdown_pct
Di writer.writerow(): hapus semua key yang sama
Import:
import numpy as np — cek setelah semua dihapus, kalau np. tidak ada lagi di file bisa dihapus 
