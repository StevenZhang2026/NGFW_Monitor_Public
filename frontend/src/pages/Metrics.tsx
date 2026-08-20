import { useEffect, useState } from 'react'
import { Card, Select, DatePicker, Space, Radio } from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import client from '../api/client'

const { RangePicker } = DatePicker

const GRANULARITY_OPTIONS = [
  { label: '原始', value: 0 },
  { label: '5 分钟', value: 300 },
  { label: '15 分钟', value: 900 },
  { label: '1 小时', value: 3600 },
  { label: '1 天', value: 86400 },
]

function Metrics() {
  const [devices, setDevices] = useState<any[]>([])
  const [metricDefs, setMetricDefs] = useState<any[]>([])
  const [selectedDevice, setSelectedDevice] = useState<string>('')
  const [selectedMetric, setSelectedMetric] = useState<string>('')
  const [granularity, setGranularity] = useState<number>(300)
  const [timeRange, setTimeRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(1, 'hour'),
    dayjs(),
  ])
  const [chartData, setChartData] = useState<any>(null)

  useEffect(() => {
    client.get('/devices').then(res => setDevices(res.data.items))
    client.get('/metrics/definitions').then(res => setMetricDefs(res.data.items))
  }, [])

  useEffect(() => {
    if (!selectedDevice || !selectedMetric) return
    const [start, end] = timeRange
    client.get('/metrics/data', {
      params: {
        device_id: selectedDevice,
        metric_name: selectedMetric,
        start: start.toISOString(),
        end: end.toISOString(),
        granularity,
      }
    }).then(res => setChartData(res.data))
  }, [selectedDevice, selectedMetric, granularity, timeRange])

  const metricInfo = metricDefs.find(m => m.name === selectedMetric)

  const buildChartOption = () => {
    if (!chartData || chartData.points.length === 0) return null

    const fmt = (v: number) => v != null ? Number(v.toFixed(2)) : v
    const hasInstances = chartData.points.some((p: any) => p.instance)
    const unit = metricInfo?.unit || ''
    const tooltipCfg = { trigger: 'axis', valueFormatter: (v: number) => `${fmt(v)} ${unit}` }
    const yAxisCfg = { type: 'value', name: unit, axisLabel: { formatter: (v: number) => fmt(v) } }

    if (hasInstances) {
      const instances = [...new Set(chartData.points.map((p: any) => p.instance).filter(Boolean))] as string[]
      const series = instances.map((inst: string) => {
        const instPoints = chartData.points.filter((p: any) => p.instance === inst)
        return {
          name: inst,
          type: 'line',
          smooth: true,
          data: instPoints.map((p: any) => [p.timestamp, fmt(granularity === 0 ? p.value : p.avg)]),
        }
      })
      return {
        tooltip: tooltipCfg,
        legend: { data: instances },
        xAxis: { type: 'time' },
        yAxis: yAxisCfg,
        dataZoom: [{ type: 'inside' }, { type: 'slider' }],
        series,
      }
    }

    return {
      tooltip: tooltipCfg,
      xAxis: { type: 'time' },
      yAxis: yAxisCfg,
      dataZoom: [{ type: 'inside' }, { type: 'slider' }],
      series: granularity === 0
        ? [{ name: metricInfo?.display_name, type: 'line', smooth: true, data: chartData.points.map((p: any) => [p.timestamp, fmt(p.value)]) }]
        : [
            { name: '平均', type: 'line', smooth: true, data: chartData.points.map((p: any) => [p.timestamp, fmt(p.avg)]) },
            { name: '最大', type: 'line', lineStyle: { type: 'dashed' }, data: chartData.points.map((p: any) => [p.timestamp, fmt(p.max)]) },
            { name: '最小', type: 'line', lineStyle: { type: 'dashed' }, data: chartData.points.map((p: any) => [p.timestamp, fmt(p.min)]) },
          ],
    }
  }

  const chartOption = buildChartOption()

  const categories = [...new Set(metricDefs.map(m => m.category))]

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          style={{ width: 200 }}
          value={selectedDevice}
          onChange={setSelectedDevice}
          options={devices.map(d => ({ label: d.name, value: d.id }))}
          placeholder="选择设备"
        />
        <Select
          style={{ width: 200 }}
          value={selectedMetric}
          onChange={setSelectedMetric}
          placeholder="选择指标"
        >
          {categories.map(cat => (
            <Select.OptGroup key={cat} label={cat}>
              {metricDefs.filter(m => m.category === cat && m.enabled).map(m => (
                <Select.Option key={m.name} value={m.name}>{m.display_name}</Select.Option>
              ))}
            </Select.OptGroup>
          ))}
        </Select>
        <RangePicker
          showTime
          value={timeRange}
          onChange={(v) => v && setTimeRange(v as [dayjs.Dayjs, dayjs.Dayjs])}
        />
        <Radio.Group
          value={granularity}
          onChange={e => setGranularity(e.target.value)}
          optionType="button"
          options={GRANULARITY_OPTIONS}
        />
      </Space>

      <Card title={metricInfo?.display_name || '请选择指标'}>
        {chartOption
          ? <ReactECharts option={chartOption} style={{ height: 400 }} />
          : <p>选择设备和指标查看数据</p>
        }
      </Card>
    </div>
  )
}

export default Metrics
