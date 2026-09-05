import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
});

export const sendMessage = async (message, sessionId) => {
  const payload = { message };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  const response = await api.post('/chat', payload);
  return response.data;
};

export const getHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export const getVendors = async () => {
  const response = await api.get('/vendors');
  return response.data.vendors || [];
};
