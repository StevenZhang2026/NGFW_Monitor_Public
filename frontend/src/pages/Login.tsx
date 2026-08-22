import { Form, Input, Button, Card, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

function Login() {
  const navigate = useNavigate()

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const res = await client.post('/auth/login', values)
      localStorage.setItem('access_token', res.data.access_token)
      localStorage.setItem('refresh_token', res.data.refresh_token)
      navigate('/dashboard')
    } catch {
      message.error('登录失败，请检查用户名和密码')
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card title="防火墙集中监控系统" style={{ width: 400 }}>
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}

export default Login
