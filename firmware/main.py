from machine import Pin, I2C
import time
import math

i2c = I2C(
    0,
    sda=Pin(0),
    scl=Pin(1),
    freq=400000
)

PCA_ADDRESSES = (0x40, 0x41)

SERVO_FREQ = 50
MIN_US = 600
MAX_US = 2400

LEGS = ("LF", "LM", "LR", "RF", "RM", "RR")

DIRECTION = [1] * 18

CENTER = [90.0] * 18
ANGLE_MIN = 45
ANGLE_MAX = 135
GAIT_PERIOD = 2.0
STRIDE = 22.0
LIFT = 18.0
TIBIA_LIFT = 12.0
SWING_FRACTION = 0.30
UPDATE_DT = 0.025
MODE = "stand"
TRIPOD_A = (0, 2, 4)
TRIPOD_B = (1, 3, 5)

MODE1 = 0x00
PRESCALE = 0xFE
LED0_ON_L = 0x06
RESTART = 0x80
SLEEP = 0x10
AI = 0x20

class PCA9685:
    def __init__(self, bus, address):
        self.bus = bus
        self.address = address

        self.write(MODE1, 0x00)
        time.sleep_ms(10)
        self.set_frequency(SERVO_FREQ)

    def write(self, register, value):
        self.bus.writeto_mem(
            self.address,
            register,
            bytes([value & 0xFF])
        )

    def read(self, register):
        return self.bus.readfrom_mem(
            self.address,
            register,
            1
        )[0]

    def set_frequency(self, frequency):
        prescale = int(
            round(25000000 / (4096 * frequency)) - 1
        )

        old_mode = self.read(MODE1)
        self.write(MODE1, (old_mode & 0x7F) | SLEEP)
        self.write(PRESCALE, prescale)
        self.write(MODE1, old_mode)
        time.sleep_ms(5)
        self.write(MODE1, old_mode | RESTART | AI)

    def set_pwm(self, channel, on_count, off_count):
        register = LED0_ON_L + 4 * channel

        data = bytes([
            on_count & 0xFF,
            (on_count >> 8) & 0x0F,
            off_count & 0xFF,
            (off_count >> 8) & 0x0F
        ])

        self.bus.writeto_mem(
            self.address,
            register,
            data
        )

    def set_servo_us(self, channel, pulse_us):
        pulse_us = max(400, min(2600, pulse_us))

        # 12-bit PWM period at the configured frequency.
        period_us = 1000000.0 / SERVO_FREQ
        ticks = int(pulse_us * 4096 / period_us)

        self.set_pwm(channel, 0, ticks)

    def set_angle(self, channel, angle):
        angle = max(0.0, min(180.0, angle))
        pulse = MIN_US + (MAX_US - MIN_US) * angle / 180.0
        self.set_servo_us(channel, int(pulse))


found = i2c.scan()
print("I2C devices:", [hex(x) for x in found])

for address in PCA_ADDRESSES:
    if address not in found:
        raise RuntimeError(
            "PCA9685 not found at " + hex(address) +
            ". Check wiring and address jumpers."
        )

pca1 = PCA9685(i2c, PCA_ADDRESSES[0])
pca2 = PCA9685(i2c, PCA_ADDRESSES[1])

drivers = (pca1, pca2)

def set_servo(servo_id, relative_angle):
    board_index = servo_id // 16
    channel = servo_id % 16

    angle = (
        CENTER[servo_id]
        + DIRECTION[servo_id] * relative_angle
    )

    angle = max(ANGLE_MIN, min(ANGLE_MAX, angle))

    drivers[board_index].set_angle(channel, angle)


def set_leg(leg_index, coxa, femur, tibia):
    base = leg_index * 3

    set_servo(base, coxa)
    set_servo(base + 1, femur)
    set_servo(base + 2, tibia)


def stand():
    for leg in range(6):
        set_leg(leg, 0, 0, 0)

    time.sleep(0.5)


def smoothstep(x):
    """Smooth interpolation from 0 to 1."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def leg_motion(phase):
    if phase < SWING_FRACTION:
        u = phase / SWING_FRACTION
        s = smoothstep(u)

        coxa = STRIDE * (1.0 - 2.0 * s)

        lift_curve = math.sin(math.pi * u)

        femur = -LIFT * lift_curve
        tibia = -TIBIA_LIFT * lift_curve

    else:
        u = (phase - SWING_FRACTION) / (
            1.0 - SWING_FRACTION
        )
        s = smoothstep(u)

        coxa = -STRIDE + 2.0 * STRIDE * s
        femur = 0.0
        tibia = 0.0

    return coxa, femur, tibia


def walk_cycle(start_time):
    elapsed = time.ticks_diff(
        time.ticks_ms(), start_time
    ) / 1000.0

    phase = (elapsed / GAIT_PERIOD) % 1.0

    for leg in range(6):
        if leg in TRIPOD_A:
            leg_phase = phase
        else:
            leg_phase = (phase + 0.5) % 1.0

        coxa, femur, tibia = leg_motion(leg_phase)
        set_leg(leg, coxa, femur, tibia)


print("POD90 controller ready.")
print("Mode:", MODE)

stand()

if MODE == "walk":
    start = time.ticks_ms()

    while True:
        walk_cycle(start)
        time.sleep(UPDATE_DT)

else:
    while True:
        time.sleep(1)
