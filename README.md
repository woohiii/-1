# ROBOTICS_PROJECT

SO-101 리더암 2개 + 팔로워암 2개를 캘리브레이션하기 위한 래퍼 스크립트입니다.
실제 캘리브레이션 로직은 `lerobot` 패키지가 제공하며, 이 프로젝트는 4개 팔을
한 번에 또는 개별적으로 다루기 위한 얇은 CLI 래퍼입니다.

## 실행 방법

`lerobot` 패키지를 임포트하므로 반드시 lerobot 저장소의 uv venv로 실행해야 합니다:

```bash
uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --all
```

## 최초 사용 전

`calibration/arms.json`의 `port` 값을 실제 USB 장치 경로로 수정하세요.
장치 경로는 다음 명령으로 확인할 수 있습니다:

```bash
uv run --project /home/youngchan/lerobot lerobot-find-port
```

## 사용 예시

```bash
# arms.json 검증만 (하드웨어 불필요)
uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --self-test

# 4개 팔 순서대로 전부 캘리브레이션
uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --all

# 특정 팔 하나만 캘리브레이션
uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --id leader_left

# 4개 팔의 캘리브레이션 상태 확인 (calibration_report.json 저장)
uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --verify
```

## 카메라 프리뷰 (camera_preview.py)

`calibration/camera_preview.py`는 카메라 3대를 동시에 창 3개로 띄워 보여줍니다:
Astra S 깊이카메라(적외선 모드, "Astra S IR" 창)와 손목 카메라 2대("Wrist 1",
"Wrist 2" 창). `q` 키를 누르면 종료됩니다.

**주의: `calibrate_arms.py`와 다른 venv로 실행해야 합니다.** 이 스크립트는
GUI가 가능한 OpenCV 빌드가 필요한데, `~/lerobot_song_venv`에만 있습니다.
`/home/youngchan/lerobot`의 uv venv는 headless opencv라서 `cv2.imshow`가
에러를 냅니다. 즉 `uv run --project /home/youngchan/lerobot ...`로 실행하면
안 됩니다.

**주의: Astra S는 반드시 별도 터미널의 별도 프로세스로 먼저 실행해야 합니다.**
OpenNI2(Astra S)와 OpenCV VideoCapture(손목캠)를 같은 프로세스에서 같이 돌리면
OpenNI2의 USB 이벤트 스레드가 우선순위를 못 받아서 `read_frame()`이 영원히
멈추는 문제가 실측으로 확인됐습니다(py-spy로 확인). 그래서 이 스크립트는 Astra
장치를 직접 열지 않고, `astra_s_ir_hub.py`가 `/tmp/vsp_astra_ir.png`에 발행한
프레임을 읽기만 합니다.

**추가로: 이 Astra S 유닛은 단독 프로세스로 돌려도 수십 초~수 분 뒤에
`read_frame()`이 다시 멈추는 문제가 있습니다** (py-spy로 `astra_s_ir_hub.py`
단독 실행 상태에서도 재현 확인 - 이 프로젝트 코드 문제가 아니라 이 장치/드라이버
자체의 고질적인 불안정성). 그래서 `astra_s_ir_hub.py`를 직접 실행하는 대신,
발행 파일이 멈추면(8초 이상 갱신 없음) 자동으로 죽이고 재시작해주는 워치독을
씁니다:

```bash
# 터미널 1: Astra S 워치독 (멈추면 자동 재시작, headless)
./calibration/run_astra_ir_watchdog.sh

# 터미널 2: 3-윈도우 프리뷰 (Astra IR은 위 프로세스가 발행한 파일을 읽음)
~/lerobot_song_venv/bin/python calibration/camera_preview.py
```

워치독이 재시작하는 동안 "Astra S IR" 창은 몇 초간 멈췄다가 다시 갱신됩니다 -
완전히 끊기지 않고 자동 복구되는 것이 정상 동작입니다.

```bash
# 하드웨어 없이 cameras.json 검증 + 손목 카메라 인덱스 확인 + IR 발행 여부 확인
~/lerobot_song_venv/bin/python calibration/camera_preview.py --self-test
```

Astra S는 한 번에 한 프로세스만 열 수 있으므로, `astra_s_ir_hub.py` 실행 전에
다른 `astra_s_*.py` 스크립트가 켜져 있지 않은지 먼저 확인하세요.

손목 카메라 이름(`calibration/cameras.json`의 `wrist_1_name`/`wrist_2_name`)은
`v4l2-ctl --list-devices` 출력에서 매칭되는 USB 제품명 일부 문자열입니다.
장치 경로(`/dev/videoN`)가 바뀌어도 이름으로 다시 찾으므로 그대로 두면 됩니다.
