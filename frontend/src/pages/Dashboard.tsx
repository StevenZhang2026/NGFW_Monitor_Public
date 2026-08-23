import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Select, Space } from 'antd'
import ReactECharts from 'echarts-for-react'
import client from '../api/client'

function formatKB(kb: number): string {
  if (kb >= 1e6) return (kb / 1e6).toFixed(1) + ' GB'
  if (kb >= 1e3) return (kb / 1e3).toFixed(1) + ' MB'
  return kb.toFixed(0) + ' KB'
}

const TIME_RANGES = [
  { value: '24h', label: '最近24小时' },
  { value: '7d', label: '最近1周' },
  { value: '30d', label: '最近1月' },
]

const RANGE_MS: Record<string, number> = {
  '24h': 86400000,
  '7d': 7 * 86400000,
  '30d': 30 * 86400000,
}

function Dashboard() {
  const [devices, setDevices] = useState<any[]>([])
  const [selectedDevice, setSelectedDevice] = useState<string>('')
  const [metrics, setMetrics] = useState<any[]>([])
  const [activeAlerts, setActiveAlerts] = useState<number>(0)
  const [timeRange, setTimeRange] = useState<string>('24h')
  const [cpuData, setCpuData] = useState<any>(null)
  const [pdData, setPdData] = useState<any>(null)
  const [appTrend, setAppTrend] = useState<any>(null)
  const [threatTrend, setThreatTrend] = useState<any>(null)

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
    client.get('/alerts/active-count').then(res => {
      setActiveAlerts(res.data.count)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedDevice) return
    const end = new Date().toISOString()
    const start = new Date(Date.now() - RANGE_MS[timeRange]).toISOString()
    const granularity = timeRange === '24h' ? 300 : timeRange === '7d' ? 3600 : 7200

    client.get('/metrics/data', {
      params: { device_id: selectedDevice, metric_name: 'cpu_usage', start, end, granularity }
    }).then(res => setCpuData(res.data)).catch(() => setCpuData({ points: [] }))

    client.get('/metrics/data', {
      params: { device_id: selectedDevice, metric_name: 'packet_descriptor', start, end, granularity }
    }).then(res => setPdData(res.data)).catch(() => setPdData({ points: [] }))

    const accParams: any = { start, end, top_n: 10 }
    accParams.device_id = selectedDevice

    client.get('/metrics/acc-trend', { params: { ...accParams, metric_name: 'acc_application' } })
      .then(res => setAppTrend(res.data)).catch(() => setAppTrend(null))

    client.get('/metrics/acc-trend', { params: { ...accParams, metric_name: 'acc_threat' } })
      .then(res => setThreatTrend(res.data)).catch(() => setThreatTrend(null))
  }, [selectedDevice, timeRange])

  const cpuOption = cpuData ? {
    tooltip: { trigger: 'axis' },
    grid: { top: 30, bottom: 30, left: 50, right: 20 },
    xAxis: { type: 'time', axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [{
      name: 'CPU',
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.3 },
      data: cpuData.points.map((p: any) => [p.timestamp, p.avg ?? p.value]),
    }],
  } : null

  const pdOption = pdData ? {
    tooltip: { trigger: 'axis' },
    grid: { top: 30, bottom: 30, left: 50, right: 20 },
    xAxis: { type: 'time', axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [{
      name: 'Packet Descriptor',
      type: 'line',
      smooth: true,
      itemStyle: { color: '#faad14' },
      lineStyle: { color: '#faad14' },
      areaStyle: { opacity: 0.3, color: '#faad14' },
      data: pdData.points.map((p: any) => [p.timestamp, p.avg ?? p.value]),
    }],
  } : null

  const appChartOption = appTrend && appTrend.items.length > 0 ? (() => {
    const allTimestamps = new Set<string>()
    for (const item of appTrend.items) {
      for (const p of (appTrend.series[item] || [])) {
        allTimestamps.add(p.timestamp)
      }
    }
    const sortedTs = Array.from(allTimestamps).sort()

    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          let html = params[0]?.axisValueLabel + '<br/>'
          for (const p of params) {
            if (p.value[1] > 0) {
              html += `${p.marker} ${p.seriesName}: ${formatKB(p.value[1] / 1024)}<br/>`
            }
          }
          return html
        },
      },
      legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 10 } },
      grid: { top: 30, bottom: 55, left: 60, right: 20 },
      xAxis: { type: 'time', axisLabel: { fontSize: 10 } },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (v: number) => formatKB(v / 1024) },
      },
      series: appTrend.items.map((item: string) => {
        const dataMap = new Map<string, number>()
        for (const p of (appTrend.series[item] || [])) {
          dataMap.set(p.timestamp, p.value)
        }
        return {
          name: item,
          type: 'line',
          stack: 'traffic',
          areaStyle: {},
          smooth: true,
          data: sortedTs.map(ts => [ts, dataMap.get(ts) || 0]),
        }
      }),
    }
  })() : null

  const threatChartOption = threatTrend && threatTrend.items.length > 0 ? {
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 10 } },
    grid: { top: 30, bottom: 55, left: 50, right: 20 },
    xAxis: { type: 'time', axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '次数' },
    series: threatTrend.items.map((item: string) => ({
      name: item.length > 25 ? item.slice(0, 23) + '...' : item,
      type: 'line',
      smooth: true,
      data: (threatTrend.series[item] || []).map((p: any) => [p.timestamp, p.value]),
    })),
  } : null

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Select
            style={{ width: 200 }}
            value={selectedDevice}
            onChange={setSelectedDevice}
            options={devices.map(d => ({ label: d.name, value: d.id }))}
            placeholder="选择设备"
          />
          <Select
            style={{ width: 140 }}
            value={timeRange}
            onChange={setTimeRange}
            options={TIME_RANGES}
          />
        </Space>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="设备总数" value={devices.length} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="在线设备" value={devices.filter(d => d.status === 'online').length} valueStyle={{ color: '#3f8600' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="监控指标" value={metrics.filter(m => m.enabled).length} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="活跃告警" value={activeAlerts} valueStyle={{ color: activeAlerts > 0 ? '#cf1322' : undefined }} /></Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12} style={{ marginBottom: 16 }}>
          <Card title="CPU 使用率" size="small" bodyStyle={{ padding: '8px 12px' }}>
            {cpuOption
              ? <ReactECharts option={cpuOption} style={{ height: 260 }} />
              : <p style={{ color: '#999', textAlign: 'center', padding: 40 }}>加载中...</p>}
          </Card>
        </Col>
        <Col span={12} style={{ marginBottom: 16 }}>
          <Card title="Packet Descriptor" size="small" bodyStyle={{ padding: '8px 12px' }}>
            {pdOption
              ? <ReactECharts option={pdOption} style={{ height: 260 }} />
              : <p style={{ color: '#999', textAlign: 'center', padding: 40 }}>加载中...</p>}
          </Card>
        </Col>
        <Col span={12} style={{ marginBottom: 16 }}>
          <Card title="应用流量 Top 10" size="small" bodyStyle={{ padding: '8px 12px' }}>
            {appChartOption
              ? <ReactECharts option={appChartOption} style={{ height: 260 }} />
              : <p style={{ color: '#999', textAlign: 'center', padding: 40 }}>暂无数据</p>}
          </Card>
        </Col>
        <Col span={12} style={{ marginBottom: 16 }}>
          <Card title="威胁 Top 10" size="small" bodyStyle={{ padding: '8px 12px' }}>
            {threatChartOption
              ? <ReactECharts option={threatChartOption} style={{ height: 260 }} />
              : <p style={{ color: '#999', textAlign: 'center', padding: 40 }}>暂无数据</p>}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
