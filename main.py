import asyncio
import logging
import random

from pathlib import Path

import can
import cantools

IGNORED_IDS = []
VOLUME_TICKS_CAN_ID = 0x3c2
VOLUME_FLICK_INTERVAL = 4.0

def configure_logger(name, level, file=None, formatter=None, propagate=False):
	logger = logging.getLogger(name)
	logger.setLevel(level)
	logger.propagate = propagate

	if file:
		Path(file).unlink(missing_ok=True)
		file_handler = logging.FileHandler(file)
		file_handler.setLevel(level)
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler)

	if name == "Flick":
		console_handler = logging.StreamHandler()
		console_handler.setLevel(level)
		console_handler.setFormatter(formatter)
		logger.addHandler(console_handler)

	return logger

common_formatter = logging.Formatter('%(asctime)s-%(name)s-%(levelname)s: %(message)s', '%H:%M:%S')
logging.formatter = common_formatter
can_logger = configure_logger("CAN", logging.DEBUG, file="can.log", formatter=common_formatter)
flick_logger = configure_logger("Flick", logging.DEBUG, formatter=common_formatter)


def create_signal_dict(message, specified_signals, default_value=0) -> dict[str, int]:
	# Initialize all signals with a default value
	signals = {signal.name: default_value for signal in message.signals}

	# Find the multiplexer signal
	multiplexer_signal = next((s for s in message.signals if s.is_multiplexer), None)

	# Update with specified signals and determine the multiplexer value
	multiplexer_value = None
	for signal in message.signals:
		if signal.name in specified_signals:
			signals[signal.name] = specified_signals[signal.name]
			if signal.multiplexer_ids is not None:
				# Assuming the first ID in multiplexer_ids as the correct value
				multiplexer_value = signal.multiplexer_ids[0]

	# Set the multiplexer signal if it's found and needed
	if multiplexer_signal and multiplexer_value is not None:
		signals[multiplexer_signal.name] = multiplexer_value

	return signals


async def flick_volume(bus: can.BusABC, dbc: cantools.db.Database) -> None:
	volume_message = dbc.get_message_by_frame_id(VOLUME_TICKS_CAN_ID)
	signals = create_signal_dict(volume_message,{'VCLEFT_swcLeftScrollTicks': -1})
	while True:
		jitter = (random.randint(0, 4000) / 1000) - 2
		interval = VOLUME_FLICK_INTERVAL + jitter
		flick_logger.info(f"Flicking volume in {interval:.4f} seconds")
		await asyncio.sleep(interval)

		flick_logger.info("Flicking volume")

		signals['VCLEFT_swcLeftScrollTicks'] = -1
		encoded_data = volume_message.encode(signals)
		can_frame = can.Message(arbitration_id=VOLUME_TICKS_CAN_ID, data=bytearray(encoded_data), is_extended_id=False)
		bus.send(can_frame)
		await asyncio.sleep(0.01)

		signals['VCLEFT_swcLeftScrollTicks'] = 1
		encoded_data = volume_message.encode(signals)
		can_frame.data = bytearray(encoded_data)
		bus.send(can_frame)


async def print_frames(bus: can.BusABC, dbc: cantools.db.Database):
	while True:
		message = bus.recv()
		if not message or message.arbitration_id in IGNORED_IDS:
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

		await asyncio.sleep(0.0001)


async def main() -> None:
	dbc = cantools.db.can.database.Database()
	dbc.add_dbc_file('model3_dbc/Model3CAN.dbc')
	bus = can.interface.Bus(bustype='socketcan', channel='can0', bitrate=500000)
	flick_volume_task = asyncio.create_task(flick_volume(bus, dbc))
	print_frames_task = asyncio.create_task(print_frames(bus, dbc))
	await asyncio.gather(flick_volume_task, print_frames_task, return_exceptions=True)


if __name__ == '__main__':

	asyncio.run(main())
