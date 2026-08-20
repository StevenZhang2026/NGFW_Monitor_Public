from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.metric import MetricData
from app.models.user import User, UserRole
from app.auth.security import require_role
from app.collectors.file_upload import FileUploadCollector

router = APIRouter()


@router.post("/acc")
async def upload_acc_data(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    data_type: str = Form(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    if not file.filename.endswith((".csv", ".CSV")):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    collector = FileUploadCollector()

    try:
        results = await collector.parse_csv(content, device_id, data_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    imported = 0
    for result in results:
        if result.success:
            data_point = MetricData(
                timestamp=result.timestamp,
                device_id=result.device_id,
                metric_name=result.metric_name,
                value=result.value,
                labels=result.labels or None,
            )
            session.add(data_point)
            imported += 1

    await session.commit()

    time_range = {}
    if results:
        timestamps = [r.timestamp for r in results if r.success]
        if timestamps:
            time_range = {
                "start": str(min(timestamps)),
                "end": str(max(timestamps)),
            }

    return {
        "status": "success",
        "records_imported": imported,
        "time_range": time_range,
    }
