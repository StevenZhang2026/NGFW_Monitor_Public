from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.models.alert import AlertType


@asynccontextmanager
async def _get_session():
    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@dataclass
class AlertEvaluation:
    triggered: bool
    message: str
    value: float | None = None
    predicted_value: float | None = None
    predicted_at: datetime | None = None


class BaseAlertRule(ABC):
    alert_type: AlertType

    @abstractmethod
    async def evaluate(self, metric_name: str, device_id: str, condition: dict) -> AlertEvaluation:
        ...


class ThresholdAlertRule(BaseAlertRule):
    alert_type = AlertType.threshold

    async def evaluate(self, metric_name: str, device_id: str, condition: dict) -> AlertEvaluation:
        from sqlalchemy import text

        operator = condition["operator"]
        threshold = condition["value"]
        duration = condition.get("duration", 300)

        async with _get_session() as session:
            query = text(f"""
                SELECT AVG(value) as avg_val
                FROM metric_data
                WHERE device_id = :device_id
                  AND metric_name = :metric_name
                  AND timestamp > NOW() - INTERVAL '{int(duration)} seconds'
            """)
            result = await session.execute(query, {
                "device_id": device_id,
                "metric_name": metric_name,
            })
            row = result.fetchone()

        if row is None or row.avg_val is None:
            return AlertEvaluation(triggered=False, message="No data")

        avg_val = row.avg_val
        triggered = self._compare(avg_val, operator, threshold)

        message = f"{metric_name} = {avg_val:.2f} {operator} {threshold} (over {duration}s)"
        return AlertEvaluation(triggered=triggered, message=message, value=avg_val)

    def _compare(self, value: float, operator: str, threshold: float) -> bool:
        ops = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
               "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
               "==": lambda a, b: a == b}
        return ops.get(operator, lambda a, b: False)(value, threshold)


class AnomalyAlertRule(BaseAlertRule):
    alert_type = AlertType.anomaly

    async def evaluate(self, metric_name: str, device_id: str, condition: dict) -> AlertEvaluation:
        from sqlalchemy import text
        import numpy as np

        lookback_hours = condition.get("lookback_hours", 24)
        z_threshold = condition.get("z_threshold", 3.0)

        async with _get_session() as session:
            query = text(f"""
                SELECT value FROM metric_data
                WHERE device_id = :device_id
                  AND metric_name = :metric_name
                  AND timestamp > NOW() - INTERVAL '{int(lookback_hours)} hours'
                ORDER BY timestamp
            """)
            result = await session.execute(query, {
                "device_id": device_id,
                "metric_name": metric_name,
            })
            rows = result.fetchall()

        if len(rows) < 10:
            return AlertEvaluation(triggered=False, message="Insufficient data for anomaly detection")

        values = np.array([r.value for r in rows])
        current = values[-1]
        mean = np.mean(values[:-1])
        std = np.std(values[:-1])

        if std == 0:
            return AlertEvaluation(triggered=False, message="Zero variance")

        z_score = abs(current - mean) / std
        triggered = z_score > z_threshold

        message = f"{metric_name} Z-score = {z_score:.2f} (threshold: {z_threshold})"
        return AlertEvaluation(triggered=triggered, message=message, value=current)


class PredictionAlertRule(BaseAlertRule):
    alert_type = AlertType.prediction

    async def evaluate(self, metric_name: str, device_id: str, condition: dict) -> AlertEvaluation:
        from sqlalchemy import text

        predict_hours = condition.get("predict_hours", 24)
        capacity = condition.get("capacity", 100)
        lookback_days = condition.get("lookback_days", 7)

        async with _get_session() as session:
            query = text(f"""
                SELECT timestamp as ds, value as y FROM metric_data
                WHERE device_id = :device_id
                  AND metric_name = :metric_name
                  AND timestamp > NOW() - INTERVAL '{int(lookback_days)} days'
                ORDER BY timestamp
            """)
            result = await session.execute(query, {
                "device_id": device_id,
                "metric_name": metric_name,
            })
            rows = result.fetchall()

        if len(rows) < 100:
            return AlertEvaluation(triggered=False, message="Insufficient data for prediction")

        try:
            import pandas as pd
            from prophet import Prophet

            df = pd.DataFrame([(r.ds, r.y) for r in rows], columns=["ds", "y"])
            model = Prophet(daily_seasonality=True, weekly_seasonality=True)
            model.fit(df)

            future = model.make_future_dataframe(periods=int(predict_hours * 60), freq="min")
            forecast = model.predict(future)

            max_predicted = forecast["yhat"].iloc[-1]
            triggered = max_predicted >= capacity

            message = (
                f"{metric_name} predicted to reach {max_predicted:.1f} "
                f"in {predict_hours}h (capacity: {capacity})"
            )
            return AlertEvaluation(
                triggered=triggered,
                message=message,
                value=float(df["y"].iloc[-1]),
                predicted_value=max_predicted,
            )
        except Exception as e:
            return AlertEvaluation(triggered=False, message=f"Prediction failed: {e}")


alert_rule_handlers: dict[AlertType, BaseAlertRule] = {
    AlertType.threshold: ThresholdAlertRule(),
    AlertType.anomaly: AnomalyAlertRule(),
    AlertType.prediction: PredictionAlertRule(),
}
