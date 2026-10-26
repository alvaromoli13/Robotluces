# Shortcuts. Everything real lives in scripts/ — this only saves typing.
# Run from this folder (lerobot/): `make help`.
SHELL := /bin/bash
.PHONY: help install verify prefetch hardware cameras calibrate teleop record replay train train-cloud rollout smoke clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:     ## install the whole environment (idempotent)
	./scripts/00_install.sh
verify:      ## check that the environment is ready
	.venv/bin/python scripts/01_verify.py
prefetch:    ## download weights and datasets up front
	./scripts/02_prefetch.sh
hardware:    ## discover serial ports and cameras
	./scripts/03_hardware.sh
cameras:     ## live camera viewer with OpenCV indices
	./scripts/06_cameras.sh
calibrate:   ## calibrate both arms
	./scripts/05_calibrate.sh follower && ./scripts/05_calibrate.sh leader
teleop:      ## teleoperation with visualization
	./scripts/10_teleop.sh
record:      ## record the dataset
	./scripts/11_record.sh
replay:      ## replay episode 0
	./scripts/12_replay.sh 0
train:       ## train locally (MPS)
	./scripts/20_train_local.sh
train-cloud: ## train on Hugging Face Jobs GPUs
	./scripts/21_train_cloud.sh
rollout:     ## the policy drives the robot
	./scripts/30_rollout.sh
smoke:       ## smoke test without a robot
	./scripts/99_smoke_sim.sh
clean:       ## delete smoke-test artifacts
	rm -rf outputs/smoke
