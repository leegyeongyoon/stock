"""연속학습 ML 파이프라인 — 누적 데이터로 조건을 고도화해 최적 조건을 찾는다.

feature_builder: 분봉(+호가) → 특징 행렬
gate: 학습된 모델 로드/예측 (라이브 진입 게이트)
(학습/walk-forward는 scripts/auto_optimize.py)
"""
