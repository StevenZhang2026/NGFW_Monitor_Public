import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Space, Tag, message, Result, Spin, Descriptions } from 'antd'
import { PlusOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import client from '../api/client'

function Devices() {
  const [devices, setDevices] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const fetchDevices = () => {
    setLoading(true)
    client.get('/devices').then(res => {
      setDevices(res.data.items)
    }).finally(() => setLoading(false))
  }

  useEffect(() => { fetchDevices() }, [])

  const handleCreate = async () => {
    const values = await form.validateFields()
    await client.post('/devices', values)
    message.success('设备添加成功')
    setModalOpen(false)
    form.resetFields()
    fetchDevices()
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '地址', dataIndex: 'hostname', key: 'hostname' },
    { title: '型号', dataIndex: 'model', key: 'model' },
    { title: '序列号', dataIndex: 'serial', key: 'serial' },
    { title: 'PAN-OS', dataIndex: 'panos_version', key: 'panos_version' },
    { title: 'HA', dataIndex: 'ha_state', key: 'ha_state' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={s === 'online' ? 'green' : 'red'}>{s}</Tag>
    },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => testConnection(record.id)}>测试连接</Button>
          <Button size="small" danger onClick={() => deleteDevice(record.id)}>删除</Button>
        </Space>
      )
    },
  ]

  const [testModalOpen, setTestModalOpen] = useState(false)
  const [testLoading, setTestLoading] = useState(false)
  const [testResults, setTestResults] = useState<{ api?: boolean; ssh?: boolean } | null>(null)
  const [testDeviceName, setTestDeviceName] = useState('')

  const testConnection = async (id: string) => {
    const device = devices.find(d => d.id === id)
    setTestDeviceName(device?.name || id)
    setTestResults(null)
    setTestLoading(true)
    setTestModalOpen(true)
    try {
      const res = await client.post(`/devices/${id}/test-connection`)
      setTestResults(res.data.results)
    } catch {
      setTestResults({ api: false, ssh: false })
    } finally {
      setTestLoading(false)
    }
  }

  const deleteDevice = async (id: string) => {
    Modal.confirm({
      title: '确认删除?',
      onOk: async () => {
        await client.delete(`/devices/${id}`)
        message.success('已删除')
        fetchDevices()
      }
    })
  }

  return (
    <div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)} style={{ marginBottom: 16 }}>
        添加设备
      </Button>
      <Table columns={columns} dataSource={devices} rowKey="id" loading={loading} />

      <Modal title="添加设备" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="设备名称" rules={[{ required: true }]}>
            <Input placeholder="PA-5450-01" />
          </Form.Item>
          <Form.Item name="hostname" label="IP/主机名" rules={[{ required: true }]}>
            <Input placeholder="10.1.1.1" />
          </Form.Item>
          <Form.Item name="ssh_username" label="SSH 用户名" rules={[{ required: true }]}>
            <Input placeholder="admin" />
          </Form.Item>
          <Form.Item name="ssh_password" label="SSH 密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
        </Form>
        <p style={{ color: '#888', fontSize: 12 }}>API Key 将通过设备凭据自动获取</p>
      </Modal>

      <Modal
        title={`连接测试 - ${testDeviceName}`}
        open={testModalOpen}
        onCancel={() => setTestModalOpen(false)}
        footer={<Button onClick={() => setTestModalOpen(false)}>关闭</Button>}
      >
        {testLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin indicator={<LoadingOutlined style={{ fontSize: 36 }} />} />
            <p style={{ marginTop: 16, color: '#888' }}>正在测试连接...</p>
          </div>
        ) : testResults ? (
          <div>
            {Object.values(testResults).every(v => v) ? (
              <Result status="success" title="所有连接正常" />
            ) : Object.values(testResults).every(v => !v) ? (
              <Result status="error" title="连接失败" subTitle="请检查设备地址和凭据" />
            ) : (
              <Result status="warning" title="部分连接异常" />
            )}
            <Descriptions column={1} bordered size="small">
              {'api' in testResults && (
                <Descriptions.Item label="API (HTTPS)">
                  {testResults.api
                    ? <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>
                    : <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
                </Descriptions.Item>
              )}
              {'ssh' in testResults && (
                <Descriptions.Item label="SSH">
                  {testResults.ssh
                    ? <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>
                    : <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
                </Descriptions.Item>
              )}
            </Descriptions>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

export default Devices
