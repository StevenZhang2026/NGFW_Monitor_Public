import { useState, useEffect } from 'react'
import { Card, Table, Button, Tabs, Tag, Space, Modal, Form, Input, Select, Switch, message, Popconfirm, TimePicker, InputNumber } from 'antd'
import dayjs from 'dayjs'
import { DownloadOutlined, PlayCircleOutlined, PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import client from '../api/client'

function cronToText(cron: string): string {
  if (!cron) return '-'
  const parts = cron.trim().split(/\s+/)
  if (parts.length < 5) return cron

  const [minute, hour, dayOfMonth, , dayOfWeek] = parts
  const weekDays: Record<string, string> = { '0': '日', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '日' }

  if (dayOfMonth !== '*' && dayOfMonth !== '?') {
    return `每月${dayOfMonth}日 ${hour}:${minute.padStart(2, '0')}`
  }
  if (dayOfWeek !== '*' && dayOfWeek !== '?') {
    const dayText = weekDays[dayOfWeek] || dayOfWeek
    return `每周${dayText} ${hour}:${minute.padStart(2, '0')}`
  }
  if (hour !== '*') {
    return `每天 ${hour}:${minute.padStart(2, '0')}`
  }
  return cron
}

const METRIC_OPTIONS = [
  { label: 'CPU 使用率', value: 'cpu_usage' },
  { label: '内存使用率', value: 'memory_usage' },
  { label: '活跃会话数', value: 'session_count' },
  { label: 'Packet Descriptor', value: 'packet_descriptor' },
  { label: '应用流量 Top 10', value: 'acc_application' },
  { label: '威胁统计', value: 'acc_threat' },
]

const TYPE_LABELS: Record<string, string> = {
  weekly: '周报',
  monthly: '月报',
  custom: '自定义',
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  generating: { color: 'processing', text: '生成中' },
  success: { color: 'success', text: '成功' },
  failed: { color: 'error', text: '失败' },
}

function Reports() {
  const [templates, setTemplates] = useState<any[]>([])
  const [history, setHistory] = useState<any[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form] = Form.useForm()

  const loadTemplates = () => {
    client.get('/reports/templates').then(res => setTemplates(res.data.items)).catch(() => {})
  }
  const loadHistory = () => {
    client.get('/reports/history').then(res => setHistory(res.data.items)).catch(() => {})
  }

  useEffect(() => { loadTemplates(); loadHistory() }, [])

  const handleSubmit = async (values: any) => {
    const time = values.schedule_time ? dayjs(values.schedule_time).format('HH:mm') : '08:00'
    const [hour, minute] = time.split(':')
    let schedule_cron = ''
    if (values.schedule_freq === 'daily') {
      schedule_cron = `${parseInt(minute)} ${parseInt(hour)} * * *`
    } else if (values.schedule_freq === 'monthly') {
      schedule_cron = `${parseInt(minute)} ${parseInt(hour)} ${values.schedule_day_of_month || 1} * *`
    } else {
      schedule_cron = `${parseInt(minute)} ${parseInt(hour)} * * ${values.schedule_day_of_week ?? 1}`
    }

    const payload = {
      ...values,
      schedule_cron,
      metrics: (values.metric_names || []).map((m: string) => ({ metric: m, analysis: ['trend', 'predict', 'top10', 'severity_breakdown'] })),
      recipients: values.recipients_text ? values.recipients_text.split(/[,;\n]/).map((s: string) => s.trim()).filter(Boolean) : [],
    }
    delete payload.metric_names
    delete payload.recipients_text
    delete payload.schedule_freq
    delete payload.schedule_day_of_week
    delete payload.schedule_day_of_month
    delete payload.schedule_time

    try {
      if (editingId) {
        await client.put(`/reports/templates/${editingId}`, payload)
        message.success('已更新')
      } else {
        await client.post('/reports/templates', payload)
        message.success('已创建')
      }
      setModalOpen(false)
      form.resetFields()
      setEditingId(null)
      loadTemplates()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleGenerate = async (id: string) => {
    try {
      await client.post(`/reports/templates/${id}/generate`)
      message.success('报表生成任务已提交，请稍后刷新查看')
      setTimeout(loadHistory, 3000)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '触发失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await client.delete(`/reports/templates/${id}`)
      message.success('已删除')
      loadTemplates()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleEdit = (record: any) => {
    setEditingId(record.id)
    const cron = record.schedule_cron || ''
    const parts = cron.trim().split(/\s+/)
    let schedule_freq = 'weekly'
    let schedule_day_of_week = 1
    let schedule_day_of_month = 1
    let schedule_time = dayjs('08:00', 'HH:mm')

    if (parts.length >= 5) {
      const [min, hr, dom, , dow] = parts
      schedule_time = dayjs(`${hr.padStart(2, '0')}:${min.padStart(2, '0')}`, 'HH:mm')
      if (dom !== '*' && dom !== '?') {
        schedule_freq = 'monthly'
        schedule_day_of_month = parseInt(dom)
      } else if (dow !== '*' && dow !== '?') {
        schedule_freq = 'weekly'
        schedule_day_of_week = parseInt(dow)
      } else {
        schedule_freq = 'daily'
      }
    }

    form.setFieldsValue({
      name: record.name,
      type: record.type,
      schedule_freq,
      schedule_day_of_week,
      schedule_day_of_month,
      schedule_time,
      metric_names: (record.metrics || []).map((m: any) => m.metric),
      recipients_text: (record.recipients || []).join('\n'),
      enabled: record.enabled,
    })
    setModalOpen(true)
  }

  const handleDownload = async (id: string) => {
    try {
      const res = await client.get(`/reports/history/${id}/download`, { responseType: 'blob' })
      const disposition = res.headers['content-disposition'] || ''
      const match = disposition.match(/filename="?([^"]+)"?/)
      const filename = match ? match[1] : `report_${id}.pdf`
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  const templateColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'type', key: 'type', render: (v: string) => <Tag>{TYPE_LABELS[v] || v}</Tag> },
    { title: '调度', dataIndex: 'schedule_cron', key: 'schedule_cron', render: (v: string) => cronToText(v) },
    { title: '收件人', dataIndex: 'recipients', key: 'recipients', render: (v: string[]) => v?.length ? `${v.length} 人` : '未配置' },
    { title: '状态', dataIndex: 'enabled', key: 'enabled', render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag> },
    {
      title: '操作', key: 'action', render: (_: any, record: any) => (
        <Space size="small">
          <Button size="small" icon={<PlayCircleOutlined />} onClick={() => handleGenerate(record.id)}>生成</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          {!record.builtin && (
            <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const historyColumns = [
    { title: '报表标题', dataIndex: 'title', key: 'title' },
    { title: '时间范围', key: 'period', render: (_: any, r: any) => `${r.period_start?.slice(0, 10) || ''} ~ ${r.period_end?.slice(0, 10) || ''}` },
    { title: '状态', dataIndex: 'status', key: 'status', render: (v: string) => <Tag color={STATUS_MAP[v]?.color}>{STATUS_MAP[v]?.text || v}</Tag> },
    { title: '文件大小', dataIndex: 'file_size', key: 'file_size', render: (v: number) => v ? `${(v / 1024).toFixed(0)} KB` : '-' },
    { title: '发送时间', dataIndex: 'sent_at', key: 'sent_at', render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '未发送' },
    { title: '生成时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '' },
    {
      title: '操作', key: 'action', render: (_: any, record: any) => (
        record.status === 'success' ? (
          <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(record.id)}>下载</Button>
        ) : record.error_message ? (
          <span style={{ color: '#ff4d4f', fontSize: 12 }}>{record.error_message.slice(0, 50)}</span>
        ) : null
      ),
    },
  ]

  return (
    <div>
      <h2 style={{ margin: '0 0 16px' }}>报表管理</h2>
      <Tabs
        defaultActiveKey="templates"
        items={[
          {
            key: 'templates',
            label: '报表模板',
            children: (
              <Card
                size="small"
                extra={
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingId(null); form.resetFields(); setModalOpen(true) }}>
                    新建模板
                  </Button>
                }
              >
                <Table dataSource={templates} columns={templateColumns} rowKey="id" size="small" pagination={false} />
              </Card>
            ),
          },
          {
            key: 'history',
            label: '历史报表',
            children: (
              <Card size="small" extra={<Button onClick={loadHistory}>刷新</Button>}>
                <Table
                  dataSource={history}
                  columns={historyColumns}
                  rowKey="id"
                  size="small"
                  pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] }}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title={editingId ? '编辑报表模板' : '新建报表模板'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditingId(null) }}
        onOk={() => form.submit()}
        width={600}
      >
        <Form form={form} onFinish={handleSubmit} layout="vertical" initialValues={{ type: 'weekly', enabled: true }}>
          <Form.Item name="name" label="报表名称" rules={[{ required: true }]}>
            <Input placeholder="如：防火墙周报" />
          </Form.Item>
          <Form.Item name="type" label="类型">
            <Select options={[
              { label: '周报', value: 'weekly' },
              { label: '月报', value: 'monthly' },
              { label: '自定义', value: 'custom' },
            ]} />
          </Form.Item>
          <Form.Item label="调度时间">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <Form.Item name="schedule_freq" noStyle initialValue="weekly">
                  <Select style={{ width: 100 }} options={[
                    { label: '每天', value: 'daily' },
                    { label: '每周', value: 'weekly' },
                    { label: '每月', value: 'monthly' },
                  ]} />
                </Form.Item>
                <Form.Item noStyle shouldUpdate={(prev, cur) => prev.schedule_freq !== cur.schedule_freq}>
                  {({ getFieldValue }) => {
                    const freq = getFieldValue('schedule_freq')
                    if (freq === 'weekly') {
                      return (
                        <Form.Item name="schedule_day_of_week" noStyle initialValue={1}>
                          <Select style={{ width: 80 }} options={[
                            { label: '周一', value: 1 }, { label: '周二', value: 2 },
                            { label: '周三', value: 3 }, { label: '周四', value: 4 },
                            { label: '周五', value: 5 }, { label: '周六', value: 6 },
                            { label: '周日', value: 0 },
                          ]} />
                        </Form.Item>
                      )
                    }
                    if (freq === 'monthly') {
                      return (
                        <Form.Item name="schedule_day_of_month" noStyle initialValue={1}>
                          <InputNumber min={1} max={28} addonAfter="日" style={{ width: 100 }} />
                        </Form.Item>
                      )
                    }
                    return null
                  }}
                </Form.Item>
                <Form.Item name="schedule_time" noStyle initialValue={dayjs('08:00', 'HH:mm')}>
                  <TimePicker format="HH:mm" />
                </Form.Item>
              </Space>
            </Space>
          </Form.Item>
          <Form.Item name="metric_names" label="包含指标" rules={[{ required: true, message: '至少选择一个指标' }]}>
            <Select mode="multiple" options={METRIC_OPTIONS} placeholder="选择要分析的指标" />
          </Form.Item>
          <Form.Item name="recipients_text" label="收件人邮箱" help="每行一个邮箱地址，或用逗号分隔">
            <Input.TextArea rows={3} placeholder="admin@example.com&#10;leader@example.com" />
          </Form.Item>
          <Form.Item name="enabled" label="启用自动生成" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Reports
