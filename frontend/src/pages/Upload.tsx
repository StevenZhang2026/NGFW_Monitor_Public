import { useState, useEffect } from 'react'
import { Upload as AntUpload, Alert, Button, Select, Form, Card, Table, Tag, Tabs, Space, Row, Col, Modal, message, Result, DatePicker } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import client from '../api/client'

const { RangePicker } = DatePicker

function formatKB(kb: number): string {
  if (kb >= 1e6) return (kb / 1e6).toFixed(1) + ' GB'
  if (kb >= 1e3) return (kb / 1e3).toFixed(1) + ' MB'
  return kb.toFixed(0) + ' KB'
}

const TIME_RANGES = [
  { value: '24h', label: '最近24小时' },
  { value: '7d', label: '最近1周' },
  { value: '30d', label: '最近1月' },
  { value: 'custom', label: '自定义' },
]

const RANGE_MS: Record<string, number> = {
  '24h': 86400000,
  '7d': 7 * 86400000,
  '30d': 30 * 86400000,
}

const RANKING_LIMITS = [
  { value: 50, label: '前 50 条' },
  { value: 100, label: '前 100 条' },
  { value: 200, label: '前 200 条' },
  // The firewall itself ranks and truncates to a top-N per 15-minute bucket,
  // so "全部" means everything that was collected, not the device's full list.
  { value: 0, label: '全部（已采集）' },
]

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'red',
  high: 'orange',
  medium: 'gold',
  low: 'blue',
  informational: 'default',
}

function Upload() {
  const [devices, setDevices] = useState<any[]>([])
  const [selectedDevice, setSelectedDevice] = useState<string>('')
  const [timeRange, setTimeRange] = useState<string>('7d')
  const [customRange, setCustomRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
  const [appTrend, setAppTrend] = useState<any>(null)
  const [threatTrend, setThreatTrend] = useState<any>(null)
  const [rankingLimit, setRankingLimit] = useState<number>(200)
  const [appRanking, setAppRanking] = useState<any[]>([])
  const [threatRanking, setThreatRanking] = useState<any[]>([])
  const [appTruncated, setAppTruncated] = useState(false)
  const [threatTruncated, setThreatTruncated] = useState(false)
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadForm] = Form.useForm()

  useEffect(() => {
    client.get('/devices').then(res => {
      setDevices(res.data.items)
      if (res.data.items.length > 0) {
        setSelectedDevice(res.data.items[0].id)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedDevice) return
    let start: string, end: string
    if (timeRange === 'custom') {
      if (!customRange) return
      start = customRange[0].toISOString()
      end = customRange[1].toISOString()
    } else {
      end = new Date().toISOString()
      start = new Date(Date.now() - RANGE_MS[timeRange]).toISOString()
    }
    const params: any = { start, end, device_id: selectedDevice }

    client.get('/metrics/acc-trend', { params: { ...params, metric_name: 'acc_application', top_n: 10 } })
      .then(res => setAppTrend(res.data)).catch(() => setAppTrend(null))

    client.get('/metrics/acc-trend', { params: { ...params, metric_name: 'acc_threat', top_n: 10 } })
      .then(res => setThreatTrend(res.data)).catch(() => setThreatTrend(null))

    client.get('/metrics/acc-ranking', { params: { ...params, metric_name: 'acc_application', limit: rankingLimit } })
      .then(res => { setAppRanking(res.data.items); setAppTruncated(res.data.truncated) })
      .catch(() => { setAppRanking([]); setAppTruncated(false) })

    client.get('/metrics/acc-ranking', { params: { ...params, metric_name: 'acc_threat', limit: rankingLimit } })
      .then(res => { setThreatRanking(res.data.items); setThreatTruncated(res.data.truncated) })
      .catch(() => { setThreatRanking([]); setThreatTruncated(false) })
  }, [selectedDevice, timeRange, customRange, rankingLimit])

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
      setUploadResult(res.data)
      message.success(`成功导入 ${res.data.records_imported} 条记录`)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const COLORS = ['#5470c6','#91cc75','#fac858','#ee6666','#73c0de','#3ba272','#fc8452','#9a60b4','#ea7ccc','#48b8d0']
  const appColorMap = new Map<string, string>()
  if (appTrend?.items) {
    appTrend.items.forEach((item: string, i: number) => { appColorMap.set(item, COLORS[i % COLORS.length]) })
  }

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
      legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
      grid: { top: 20, bottom: 55, left: 70, right: 20 },
      xAxis: { type: 'time' },
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
          itemStyle: { color: appColorMap.get(item) },
          data: sortedTs.map(ts => [ts, dataMap.get(ts) || 0]),
        }
      }),
    }
  })() : null

  const threatChartOption = threatTrend && threatTrend.items.length > 0 ? {
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    grid: { top: 20, bottom: 55, left: 50, right: 20 },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', name: '次数' },
    series: threatTrend.items.map((item: string) => ({
      name: item.length > 30 ? item.slice(0, 28) + '...' : item,
      type: 'line',
      smooth: true,
      data: (threatTrend.series[item] || []).map((p: any) => [p.timestamp, p.value]),
    })),
  } : null

  const appPieOption = appRanking.length > 0 ? {
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}: ${formatKB(p.value / 1024)} (${p.percent}%)` },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['30%', '65%'],
      center: ['50%', '45%'],
      data: appRanking.slice(0, 10).map(item => ({ name: item.name, value: item.bytes, itemStyle: { color: appColorMap.get(item.name) } })),
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 12 } },
    }],
  } : null

  const threatPieOption = threatRanking.length > 0 ? {
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}: ${p.value} 次 (${p.percent}%)` },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['30%', '65%'],
      center: ['50%', '45%'],
      data: threatRanking.slice(0, 10).map(item => ({ name: item.name.length > 20 ? item.name.slice(0, 18) + '...' : item.name, value: item.count })),
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 12 } },
    }],
  } : null

  const appColumns = [
    { title: '#', key: 'rank', width: 50, render: (_: any, __: any, i: number) => i + 1 },
    { title: '应用名称', dataIndex: 'name', key: 'name' },
    {
      title: '流量', dataIndex: 'bytes', key: 'bytes',
      render: (v: number) => formatKB(v / 1024),
      sorter: (a: any, b: any) => a.bytes - b.bytes,
      defaultSortOrder: 'descend' as const,
    },
    { title: '会话数', dataIndex: 'sessions', key: 'sessions', sorter: (a: any, b: any) => a.sessions - b.sessions },
    {
      title: '风险等级', dataIndex: 'risk', key: 'risk',
      render: (v: string) => {
        const colors: Record<string, string> = { '5': 'red', '4': 'orange', '3': 'gold', '2': 'blue', '1': 'green' }
        return <Tag color={colors[v] || 'default'}>{v}</Tag>
      },
      sorter: (a: any, b: any) => Number(b.risk || 0) - Number(a.risk || 0),
    },
  ]

  const threatColumns = [
    { title: '#', key: 'rank', width: 50, render: (_: any, __: any, i: number) => i + 1 },
    { title: '威胁名称', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '次数', dataIndex: 'count', key: 'count', sorter: (a: any, b: any) => a.count - b.count, defaultSortOrder: 'descend' as const },
    {
      title: '严重性', dataIndex: 'severity', key: 'severity',
      render: (v: string) => <Tag color={SEVERITY_COLORS[v] || 'default'}>{v}</Tag>,
      sorter: (a: any, b: any) => {
        const order: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1, informational: 0 }
        return (order[a.severity] ?? -1) - (order[b.severity] ?? -1)
      },
    },
    {
      title: '类别', dataIndex: 'category', key: 'category',
      sorter: (a: any, b: any) => (a.category || '').localeCompare(b.category || ''),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>ACC 数据</h2>
        <Space>
          <Select
            style={{ width: 180 }}
            value={selectedDevice}
            onChange={setSelectedDevice}
            options={devices.map(d => ({ label: d.name, value: d.id }))}
            placeholder="选择设备"
          />
          <Select style={{ width: 130 }} value={timeRange} onChange={(v) => { setTimeRange(v); if (v !== 'custom') setCustomRange(null) }} options={TIME_RANGES} />
          <Select style={{ width: 120 }} value={rankingLimit} onChange={setRankingLimit} options={RANKING_LIMITS} />
          {timeRange === 'custom' && (
            <RangePicker
              showTime={{ format: 'HH:mm' }}
              format="YYYY-MM-DD HH:mm"
              value={customRange}
              onChange={(dates) => setCustomRange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null)}
              allowClear={false}
            />
          )}
          <Button icon={<UploadOutlined />} onClick={() => { setUploadModalOpen(true); setUploadResult(null) }}>
            导入数据
          </Button>
        </Space>
      </div>

      <Tabs
        defaultActiveKey="application"
        items={[
          {
            key: 'application',
            label: '应用流量',
            children: (
              <>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={14}>
                    <Card title="应用流量 Top 10 趋势" size="small">
                      {appChartOption
                        ? <ReactECharts option={appChartOption} style={{ height: 320 }} />
                        : <p style={{ color: '#999', textAlign: 'center', padding: 60 }}>暂无应用流量数据</p>}
                    </Card>
                  </Col>
                  <Col span={10}>
                    <Card title="应用流量 Top 10 占比" size="small">
                      {appPieOption
                        ? <ReactECharts option={appPieOption} style={{ height: 320 }} />
                        : <p style={{ color: '#999', textAlign: 'center', padding: 60 }}>暂无数据</p>}
                    </Card>
                  </Col>
                </Row>
                <Card title="应用流量完整排名" size="small">
                  {appTruncated && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={`当前仅显示流量最高的 ${rankingLimit} 个应用，实际数量可能更多。切换右上角「${RANKING_LIMITS.find(l => l.value === 0)!.label}」查看完整列表。`}
                    />
                  )}
                  <Table
                    dataSource={appRanking}
                    columns={appColumns}
                    rowKey="name"
                    size="small"
                    pagination={{ defaultPageSize: 20, pageSizeOptions: ['10', '20', '50', '100'], showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'threat',
            label: '威胁统计',
            children: (
              <>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={14}>
                    <Card title="威胁 Top 10 趋势" size="small">
                      {threatChartOption
                        ? <ReactECharts option={threatChartOption} style={{ height: 320 }} />
                        : <p style={{ color: '#999', textAlign: 'center', padding: 60 }}>暂无威胁数据</p>}
                    </Card>
                  </Col>
                  <Col span={10}>
                    <Card title="威胁 Top 10 占比" size="small">
                      {threatPieOption
                        ? <ReactECharts option={threatPieOption} style={{ height: 320 }} />
                        : <p style={{ color: '#999', textAlign: 'center', padding: 60 }}>暂无数据</p>}
                    </Card>
                  </Col>
                </Row>
                <Card title="威胁完整排名" size="small">
                  {threatTruncated && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={`当前仅显示次数最高的 ${rankingLimit} 个威胁，实际数量可能更多。切换右上角「${RANKING_LIMITS.find(l => l.value === 0)!.label}」查看完整列表。`}
                    />
                  )}
                  <Table
                    dataSource={threatRanking}
                    columns={threatColumns}
                    rowKey="name"
                    size="small"
                    pagination={{ defaultPageSize: 20, pageSizeOptions: ['10', '20', '50', '100'], showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
                  />
                </Card>
              </>
            ),
          },
        ]}
      />

      <Modal
        title="导入 ACC 数据"
        open={uploadModalOpen}
        onCancel={() => setUploadModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={uploadForm} onFinish={handleUpload} layout="vertical">
          <Form.Item name="device_id" label="关联设备" rules={[{ required: true }]} initialValue={selectedDevice}>
            <Select options={devices.map(d => ({ label: d.name, value: d.id }))} placeholder="选择设备" />
          </Form.Item>
          <Form.Item name="data_type" label="数据类型" rules={[{ required: true }]}>
            <Select options={[
              { label: '应用流量 (Application/Traffic)', value: 'traffic' },
              { label: '威胁统计 (Threat)', value: 'threat' },
            ]} />
          </Form.Item>
          <Form.Item name="file" label="CSV 文件" rules={[{ required: true }]}>
            <AntUpload beforeUpload={() => false} maxCount={1} accept=".csv">
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </AntUpload>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={uploading}>上传并导入</Button>
          </Form.Item>
        </Form>
        {uploadResult && (
          <Result
            status="success"
            title={`导入完成: ${uploadResult.records_imported} 条记录`}
            subTitle={uploadResult.time_range.start ? `时间范围: ${uploadResult.time_range.start} ~ ${uploadResult.time_range.end}` : ''}
          />
        )}
      </Modal>
    </div>
  )
}

export default Upload
