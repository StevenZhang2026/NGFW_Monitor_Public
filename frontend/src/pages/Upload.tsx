import { useState, useEffect } from 'react'
import { Upload as AntUpload, Button, Select, Form, Card, message, Result } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import client from '../api/client'

function Upload() {
  const [devices, setDevices] = useState<any[]>([])
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    client.get('/devices').then(res => setDevices(res.data.items))
  }, [])

  const handleUpload = async (values: any) => {
    const formData = new FormData()
    formData.append('file', values.file.file)
    formData.append('device_id', values.device_id)
    formData.append('data_type', values.data_type)

    setUploading(true)
    try {
      const res = await client.post('/upload/acc', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(res.data)
      message.success(`成功导入 ${res.data.records_imported} 条记录`)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card title="ACC 数据上传">
      <Form form={form} onFinish={handleUpload} layout="vertical" style={{ maxWidth: 500 }}>
        <Form.Item name="device_id" label="关联设备" rules={[{ required: true }]}>
          <Select options={devices.map(d => ({ label: d.name, value: d.id }))} placeholder="选择设备" />
        </Form.Item>
        <Form.Item name="data_type" label="数据类型" rules={[{ required: true }]}>
          <Select options={[
            { label: 'Threat', value: 'threat' },
            { label: 'Traffic', value: 'traffic' },
          ]} />
        </Form.Item>
        <Form.Item name="file" label="CSV 文件" rules={[{ required: true }]}>
          <AntUpload beforeUpload={() => false} maxCount={1} accept=".csv">
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </AntUpload>
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={uploading}>
            上传并导入
          </Button>
        </Form.Item>
      </Form>

      {result && (
        <Result
          status="success"
          title={`导入完成: ${result.records_imported} 条记录`}
          subTitle={result.time_range.start ? `时间范围: ${result.time_range.start} ~ ${result.time_range.end}` : ''}
        />
      )}
    </Card>
  )
}

export default Upload
