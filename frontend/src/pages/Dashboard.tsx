import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Select, Space } from 'antd'
import ReactECharts from 'echarts-for-react'
import client from '../api/client'

function Dashboard() {
  const [devices, setDevices] = useState<any[]>([])
  const [selectedDevice, setSelectedDevice] = useState<string>('')
  const [metrics, setMetrics] = useState<any[]>([])
  const [chartData, setChartData] = useState<any>(null)

  useEffect(() => {
    client.get('/devices').then(res => {
      setDevices(res.data.items)
      if (res.data.items.length > 0) {
        setSelectedDevice(res.data.items[0].id)
      }
    })
    client.get('/metrics/definitions').then(res => {
      setMetrics(res.data.items)
    })
  }, [])

  useEffect(() => {
    if (!selectedDevice) return
    const end = new Date().toISOString()
    const start = new Date(Date.now() - 3600000).toISOString()
    client.get('/metrics/data', {
      params: { device_id: selectedDevice, metric_name: 'cpu_usage', start, end }
    }).then(res => {
      setChartData(res.data)
    }).catch(() => {
      setChartData({ points: [] })
    })
  }, [selectedDevice])

  const chartOption = chartData ? {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', name: '%' },
    series: [{
      name: 'CPU',
      type: 'line',
      smooth: true,
      data: chartData.points.map((p: any) => [p.timestamp, p.avg ?? p.value]),
    }],
  } : {}

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Select
          style={{ width: 200 }}
          value={selectedDevice}
          onChange={setSelectedDevice}
          options={devices.map(d => ({ label: d.name, value: d.id }))}
          placeholder="选择设备"
        />
      </Space>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card><Statistic title="设备总数" value={devices.length} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="在线设备" value={devices.filter(d => d.status === 'online').length} valueStyle={{ color: '#3f8600' }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="监控指标" value={metrics.filter(m => m.enabled).length} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="活跃告警" value={0} valueStyle={{ color: '#cf1322' }} /></Card>
        </Col>
      </Row>

      <Card title="CPU 使用率 (最近 1 小时)">
        {chartData ? <ReactECharts option={chartOption} style={{ height: 300 }} /> : <p>加载中...</p>}
      </Card>
    </div>
  )
}

export default Dashboard
