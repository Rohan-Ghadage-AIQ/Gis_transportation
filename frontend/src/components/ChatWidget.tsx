import React, { useState, useRef, useEffect } from 'react';
import { apiService } from '../services/api';
import type { RouteResults } from '../types/api';

interface ChatMessage {
    role: 'user' | 'model';
    content: string;
    timestamp: Date;
}

interface ChatWidgetProps {
    results: RouteResults;
    isOpen: boolean;
    onClose: () => void;
}

// Gemini sparkle icon SVG
const GeminiIcon = ({ size = 20, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
        <path d="M14 0C14 7.732 7.732 14 0 14C7.732 14 14 20.268 14 28C14 20.268 20.268 14 28 14C20.268 14 14 7.732 14 0Z" fill={color} />
    </svg>
);

export const ChatWidget: React.FC<ChatWidgetProps> = ({ results, isOpen, onClose }) => {
    const [messages, setMessages] = useState<ChatMessage[]>([
        {
            role: 'model',
            content: "Hi! I'm your VRP Analytics Assistant powered by Gemini. Ask me anything about your delivery routes, vehicles, parcels, or traffic conditions! 🚚",
            timestamp: new Date()
        }
    ]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // Auto-scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    // Focus input when opened
    useEffect(() => {
        if (isOpen) {
            setTimeout(() => inputRef.current?.focus(), 300);
        }
    }, [isOpen]);

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMessage: ChatMessage = {
            role: 'user',
            content: input.trim(),
            timestamp: new Date()
        };

        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        try {
            // Build history for context (exclude the welcome message)
            const history = messages
                .filter((_, i) => i > 0) // skip welcome
                .map(m => ({ role: m.role, content: m.content }));

            const response = await apiService.chat(userMessage.content, history);

            const botMessage: ChatMessage = {
                role: 'model',
                content: response,
                timestamp: new Date()
            };
            setMessages(prev => [...prev, botMessage]);
        } catch (err: any) {
            const errorMessage: ChatMessage = {
                role: 'model',
                content: '⚠️ Sorry, I encountered an error. Please try again.',
                timestamp: new Date()
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // Quick suggestion chips
    const suggestions = [
        "Summarize today's plan",
        "Which vehicle is most loaded?",
        "Any late deliveries?",
        "Weather impact on routes?"
    ];

    // Format message content with markdown-like rendering
    const formatContent = (content: string) => {
        // Bold: **text**
        let formatted = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Bullet points: lines starting with - or •
        formatted = formatted.replace(/^[-•]\s+(.+)$/gm, '<div style="padding-left:12px;position:relative"><span style="position:absolute;left:0">•</span>$1</div>');
        // Line breaks
        formatted = formatted.replace(/\n/g, '<br/>');
        return formatted;
    };

    return (
        <div
            className="chatbot-panel"
            style={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: isOpen ? 400 : 0,
                height: '100%',
                overflow: 'hidden',
                transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                zIndex: 40,
                display: 'flex',
                flexDirection: 'column',
                borderLeft: isOpen ? '1px solid rgba(139, 92, 246, 0.3)' : 'none',
            }}
        >
            <div style={{
                display: isOpen ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
                width: 400,
                background: 'linear-gradient(180deg, #1a1035 0%, #0f0a1e 100%)',
            }}>
                {/* Header */}
                <div style={{
                    padding: '14px 16px',
                    background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 50%, #5b21b6 100%)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    borderBottom: '1px solid rgba(139, 92, 246, 0.4)',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{
                            width: 32, height: 32, borderRadius: '50%',
                            background: 'linear-gradient(135deg, #a78bfa, #c084fc)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            boxShadow: '0 0 12px rgba(167, 139, 250, 0.5)',
                        }}>
                            <GeminiIcon size={16} color="#fff" />
                        </div>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', letterSpacing: '0.3px' }}>
                                VRP Assistant
                            </div>
                            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)', marginTop: 1 }}>
                                Powered by Gemini
                            </div>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        style={{
                            background: 'rgba(255,255,255,0.15)',
                            border: 'none',
                            borderRadius: 6,
                            width: 28, height: 28,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            cursor: 'pointer',
                            color: '#fff',
                            fontSize: 14,
                            transition: 'background 0.2s',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.25)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.15)')}
                    >
                        ✕
                    </button>
                </div>

                {/* Messages */}
                <div style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: '16px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                }}>
                    {messages.map((msg, i) => (
                        <div
                            key={i}
                            style={{
                                display: 'flex',
                                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                                animation: 'fadeInUp 0.3s ease-out',
                            }}
                        >
                            {msg.role === 'model' && (
                                <div style={{
                                    width: 26, height: 26, borderRadius: '50%',
                                    background: 'linear-gradient(135deg, #7c3aed, #a78bfa)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    marginRight: 8, flexShrink: 0, marginTop: 2,
                                    boxShadow: '0 0 8px rgba(124, 58, 237, 0.3)',
                                }}>
                                    <GeminiIcon size={12} color="#fff" />
                                </div>
                            )}
                            <div style={{
                                maxWidth: '82%',
                                padding: '10px 14px',
                                borderRadius: msg.role === 'user'
                                    ? '14px 14px 4px 14px'
                                    : '14px 14px 14px 4px',
                                background: msg.role === 'user'
                                    ? 'linear-gradient(135deg, #7c3aed, #6d28d9)'
                                    : 'rgba(139, 92, 246, 0.12)',
                                color: msg.role === 'user' ? '#fff' : '#e2d9f3',
                                fontSize: 13,
                                lineHeight: 1.5,
                                border: msg.role === 'model'
                                    ? '1px solid rgba(139, 92, 246, 0.2)'
                                    : 'none',
                                boxShadow: msg.role === 'user'
                                    ? '0 2px 8px rgba(124, 58, 237, 0.3)'
                                    : 'none',
                            }}
                                dangerouslySetInnerHTML={{ __html: formatContent(msg.content) }}
                            />
                        </div>
                    ))}

                    {/* Typing indicator */}
                    {isLoading && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 26, height: 26, borderRadius: '50%',
                                background: 'linear-gradient(135deg, #7c3aed, #a78bfa)',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                boxShadow: '0 0 8px rgba(124, 58, 237, 0.3)',
                            }}>
                                <GeminiIcon size={12} color="#fff" />
                            </div>
                            <div style={{
                                padding: '10px 16px',
                                borderRadius: '14px 14px 14px 4px',
                                background: 'rgba(139, 92, 246, 0.12)',
                                border: '1px solid rgba(139, 92, 246, 0.2)',
                                display: 'flex', gap: 4, alignItems: 'center',
                            }}>
                                <div className="typing-dot" style={{ animationDelay: '0s' }} />
                                <div className="typing-dot" style={{ animationDelay: '0.2s' }} />
                                <div className="typing-dot" style={{ animationDelay: '0.4s' }} />
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>

                {/* Suggestion chips (show only at start) */}
                {messages.length <= 1 && (
                    <div style={{
                        padding: '0 14px 12px',
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: 6,
                    }}>
                        {suggestions.map((s, i) => (
                            <button
                                key={i}
                                onClick={() => {
                                    setInput(s);
                                    setTimeout(() => {
                                        setInput(s);
                                        sendMessage();
                                    }, 0);
                                    // Direct send
                                    const userMsg: ChatMessage = { role: 'user', content: s, timestamp: new Date() };
                                    setMessages(prev => [...prev, userMsg]);
                                    setIsLoading(true);
                                    apiService.chat(s, []).then(response => {
                                        setMessages(prev => [...prev, {
                                            role: 'model',
                                            content: response,
                                            timestamp: new Date()
                                        }]);
                                    }).catch(() => {
                                        setMessages(prev => [...prev, {
                                            role: 'model',
                                            content: '⚠️ Error. Please try again.',
                                            timestamp: new Date()
                                        }]);
                                    }).finally(() => {
                                        setIsLoading(false);
                                        setInput('');
                                    });
                                }}
                                style={{
                                    padding: '6px 12px',
                                    borderRadius: 20,
                                    border: '1px solid rgba(139, 92, 246, 0.35)',
                                    background: 'rgba(139, 92, 246, 0.1)',
                                    color: '#c4b5fd',
                                    fontSize: 12,
                                    cursor: 'pointer',
                                    transition: 'all 0.2s',
                                    whiteSpace: 'nowrap',
                                }}
                                onMouseEnter={e => {
                                    e.currentTarget.style.background = 'rgba(139, 92, 246, 0.25)';
                                    e.currentTarget.style.borderColor = 'rgba(139, 92, 246, 0.6)';
                                }}
                                onMouseLeave={e => {
                                    e.currentTarget.style.background = 'rgba(139, 92, 246, 0.1)';
                                    e.currentTarget.style.borderColor = 'rgba(139, 92, 246, 0.35)';
                                }}
                            >
                                {s}
                            </button>
                        ))}
                    </div>
                )}

                {/* Input area */}
                <div style={{
                    padding: '12px 14px',
                    borderTop: '1px solid rgba(139, 92, 246, 0.2)',
                    background: 'rgba(15, 10, 30, 0.8)',
                }}>
                    <div style={{
                        display: 'flex',
                        gap: 8,
                        background: 'rgba(139, 92, 246, 0.08)',
                        border: '1px solid rgba(139, 92, 246, 0.25)',
                        borderRadius: 12,
                        padding: '4px 4px 4px 14px',
                        alignItems: 'center',
                        transition: 'border-color 0.2s',
                    }}>
                        <input
                            ref={inputRef}
                            type="text"
                            value={input}
                            onChange={e => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Ask about routes, vehicles, parcels..."
                            disabled={isLoading}
                            style={{
                                flex: 1,
                                background: 'transparent',
                                border: 'none',
                                outline: 'none',
                                color: '#e2d9f3',
                                fontSize: 13,
                                fontFamily: 'inherit',
                            }}
                        />
                        <button
                            onClick={sendMessage}
                            disabled={!input.trim() || isLoading}
                            style={{
                                width: 34, height: 34,
                                borderRadius: 8,
                                border: 'none',
                                background: input.trim()
                                    ? 'linear-gradient(135deg, #7c3aed, #6d28d9)'
                                    : 'rgba(139, 92, 246, 0.2)',
                                color: '#fff',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                cursor: input.trim() ? 'pointer' : 'default',
                                transition: 'all 0.2s',
                                flexShrink: 0,
                            }}
                        >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3 3l18 9-18 9 3-9zm0 0h9" />
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
