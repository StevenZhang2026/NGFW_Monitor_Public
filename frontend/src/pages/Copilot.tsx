import { useState, useRef, useEffect } from 'react'
import { Input, Button, Card, Spin, Typography } from 'antd'
import { SendOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import client from '../api/client'

const { Text } = Typography

interface Message {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
}

function Copilot() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '你好！我是 NGFW Monitor AI 助手。你可以用自然语言向我查询设备状态、威胁排名、流量趋势等信息。\n\n例如：\n- 最近3天威胁 Top 10\n- CPU 使用率这周怎么样\n- 当前有没有严重告警\n- 设备状态' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '', loading: true }])
    setLoading(true)

    try {
      const res = await client.post('/copilot/chat', { message: text })
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: res.data.reply }
        return next
      })
    } catch (err: any) {
      const detail = err.response?.data?.detail || '请求失败，请检查 AI 配置。'
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: `⚠️ ${detail}` }
        return next
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ height: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, overflow: 'auto', padding: '0 0 16px 0' }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
            marginBottom: 12,
          }}>
            <Card
              size="small"
              style={{
                maxWidth: '80%',
                background: msg.role === 'user' ? '#e6f4ff' : '#f5f5f5',
                border: 'none',
              }}
              bodyStyle={{ padding: '8px 12px' }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                {msg.role === 'assistant' && <RobotOutlined style={{ color: '#1677ff', marginTop: 4 }} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  {msg.loading ? (
                    <Spin size="small" />
                  ) : msg.role === 'assistant' ? (
                    <div style={{ fontSize: 13 }}>
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          table: ({ children }) => <table style={{ borderCollapse: 'collapse', width: '100%', margin: '8px 0' }}>{children}</table>,
                          th: ({ children }) => <th style={{ border: '1px solid #d9d9d9', padding: '6px 10px', background: '#fafafa', textAlign: 'left', fontSize: 12 }}>{children}</th>,
                          td: ({ children }) => <td style={{ border: '1px solid #d9d9d9', padding: '5px 10px', fontSize: 12 }}>{children}</td>,
                        }}
                      >{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <Text>{msg.content}</Text>
                  )}
                </div>
                {msg.role === 'user' && <UserOutlined style={{ color: '#1677ff', marginTop: 4 }} />}
              </div>
            </Card>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: 'flex', gap: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          onPressEnter={sendMessage}
          placeholder="输入问题，如：最近3天威胁 Top 10..."
          disabled={loading}
          size="large"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={sendMessage}
          loading={loading}
          size="large"
        />
      </div>
    </div>
  )
}

export default Copilot
