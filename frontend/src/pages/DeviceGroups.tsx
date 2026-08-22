import { useState, useEffect } from 'react'
import { Table, Button, Modal, Form, Input, Space, message, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import client from '../api/client'

interface GroupRecord {
  id: string
  name: string
  description: string | null
  device_count: number
  created_at: string
}

function DeviceGroups() {
  const [groups, setGroups] = useState<GroupRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<GroupRecord | null>(null)
  const [form] = Form.useForm()

  const fetchGroups = async () => {
    setLoading(true)
    try {
      const res = await client.get('/device-groups')
      setGroups(res.data.items)
    } catch {
      message.error('获取分组列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchGroups() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (record: GroupRecord) => {
    setEditing(record)
    form.setFieldsValue({ name: record.name, description: record.description })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editing) {
        await client.put(`/device-groups/${editing.id}`, values)
        message.success('分组已更新')
      } else {
        await client.post('/device-groups', values)
        message.success('分组已创建')
      }
      setModalOpen(false)
      fetchGroups()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await client.delete(`/device-groups/${id}`)
      message.success('分组已删除')
      fetchGroups()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const columns = [
    { title: '分组名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v: string | null) => v || '-' },
    { title: '设备数量', dataIndex: 'device_count', key: 'device_count' },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at',
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: GroupRecord) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="删除后，分组内设备将变为未分组。确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" icon={<DeleteOutlined />} danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>设备分组</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建分组</Button>
      </div>

      <Table dataSource={groups} columns={columns} rowKey="id" loading={loading} pagination={false} />

      <Modal
        title={editing ? '编辑分组' : '新建分组'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} onFinish={handleSubmit} layout="vertical">
          <Form.Item name="name" label="分组名称" rules={[{ required: true, message: '请输入分组名称' }]}>
            <Input placeholder="如：北京机房、海外节点" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选描述" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default DeviceGroups
