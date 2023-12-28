import asyncio
import logging
import random
import time
from pathlib import Path

import can
import cantools

CAN_BUS_BITRATE = 500000
CAN_DBC_FILE = Path('dbc/model3/Model3CAN.dbc')

VEHICLE_BUS_CHANNEL = 'can0'

ID3C2VCLEFT_switchStatus = 0x3c2
VOLUME_TICKS_SIGNAL_NAME = 'VCLEFT_swcLeftScrollTicks'
VOLUME_FLICK_INTERVAL = 10.0
VOLUME_FLICK_JITTER = 2


def configure_logger(name: str, level: int, file: Path = None, formatter: logging.Formatter = None,
                     propagate=False) -> logging.Logger:
	logger = logging.getLogger(name)
	logger.setLevel(level)
	logger.propagate = propagate

	if file:
		file.unlink(missing_ok=True)
		file_handler = logging.FileHandler(file)
		file_handler.setLevel(level)
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler)

	else:
		console_handler = logging.StreamHandler()
		console_handler.setLevel(level)
		console_handler.setFormatter(formatter)
		logger.addHandler(console_handler)

	return logger


common_formatter = logging.Formatter('%(asctime)s-%(name)s-%(levelname)s: %(message)s', '%H:%M:%S')
logging.formatter = common_formatter
can_logger = configure_logger("CAN", logging.DEBUG, file=Path("can.log"), formatter=common_formatter)
flick_logger = configure_logger("Flick", logging.DEBUG, formatter=common_formatter)


def create_signal_dict(message, specified_signals, default_value=0) -> dict[str, int]:
	signals = {signal.name: default_value for signal in message.signals}

	multiplexer_signal = next((s for s in message.signals if s.is_multiplexer), None)

	multiplexer_value = None
	for signal in message.signals:
		if signal.name in specified_signals:
			signals[signal.name] = specified_signals[signal.name]
			if signal.multiplexer_ids is not None:
				multiplexer_value = signal.multiplexer_ids[0]

	if multiplexer_signal and multiplexer_value is not None:
		signals[multiplexer_signal.name] = multiplexer_value

	return signals


async def flick_volume(bus: can.BusABC, dbc: cantools.db.Database) -> None:
	volume_message = dbc.get_message_by_frame_id(ID3C2VCLEFT_switchStatus)
	signals = create_signal_dict(volume_message, {VOLUME_TICKS_SIGNAL_NAME: -1})
	while True:
		jitter = (random.randint(0, 2000 * VOLUME_FLICK_JITTER) / 1000) - VOLUME_FLICK_JITTER
		interval = VOLUME_FLICK_INTERVAL + jitter
		flick_logger.info(f"Flicking volume in {interval:.4f} seconds")
		await asyncio.sleep(interval)

		flick_logger.info("Flicking volume")

		signals[VOLUME_TICKS_SIGNAL_NAME] = -1
		encoded_data = volume_message.encode(signals)
		can_frame = can.Message(arbitration_id=ID3C2VCLEFT_switchStatus, data=bytearray(encoded_data), is_extended_id=False)
		bus.send(can_frame)
		await asyncio.sleep(0.01)

		signals[VOLUME_TICKS_SIGNAL_NAME] = 1
		encoded_data = volume_message.encode(signals)
		can_frame.data = bytearray(encoded_data)
		bus.send(can_frame)


async def log_all_frames(bus: can.BusABC, dbc: cantools.db.Database):
	while True:
		message = bus.recv()
		if not message:
			continue

		try:
			decoded_message = dbc.decode_message(message.arbitration_id, message.data)
			can_logger.info(f"Received message: {decoded_message}")
		except cantools.db.errors.DecodeError as e:
			can_logger.debug(f"Decode error: {e}")
			can_logger.debug(
				f"Raw message: ID={message.arbitration_id}, Data={message.data.hex()}, Timestamp={message.timestamp}")
			continue

		except (KeyError, ValueError):
			can_logger.debug(f"Received unknown message: {message}")

		await asyncio.sleep(0.000001)


async def main() -> None:
	dbc = cantools.db.can.database.Database()
	dbc.add_dbc_file(CAN_DBC_FILE)
	vehicle_bus = can.interface.Bus(bustype='socketcan', channel=VEHICLE_BUS_CHANNEL, bitrate=CAN_BUS_BITRATE)
	flick_volume_task = asyncio.create_task(flick_volume(vehicle_bus, dbc))
	print_frames_task = asyncio.create_task(log_all_frames(vehicle_bus, dbc))
	await asyncio.gather(flick_volume_task, print_frames_task, return_exceptions=True)


if __name__ == '__main__':
	asyncio.run(main())
