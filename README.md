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
