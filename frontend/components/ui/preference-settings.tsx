import React, { useState, useEffect } from 'react';
import { Settings, Save, User, Heart, Calendar, MapPin, DollarSign, Sun, Umbrella, Camera, Utensils, Car, Hotel } from 'lucide-react';

interface UserPreferences {
  travelStyle: 'relaxed' | 'adventurous' | 'cultural' | 'foodie' | 'family';
  budgetLevel: 'budget' | 'mid' | 'luxury';
  preferredActivities: string[];
  travelSeason: 'spring' | 'summer' | 'autumn' | 'winter';
  groupSize: number;
  specialNeeds: string[];
  travelerType: 'backpacker' | 'family' | 'luxury' | 'couple' | 'elderly' | 'general';
}

interface PreferenceSettingsProps {
  onSave: (preferences: UserPreferences) => void;
  initialPreferences?: UserPreferences;
}

const defaultPreferences: UserPreferences = {
  travelStyle: 'relaxed',
  budgetLevel: 'mid',
  preferredActivities: ['sightseeing'],
  travelSeason: 'spring',
  groupSize: 2,
  specialNeeds: [],
  travelerType: 'general'
};

function PreferenceSettings({ onSave, initialPreferences = defaultPreferences }: PreferenceSettingsProps) {
  const [preferences, setPreferences] = useState<UserPreferences>(initialPreferences);
  const [isVisible, setIsVisible] = useState(false);

  const handlePreferenceChange = (key: keyof UserPreferences, value: any) => {
    setPreferences(prev => ({ ...prev, [key]: value }));
  };

  const handleActivityToggle = (activity: string) => {
    setPreferences(prev => ({
      ...prev,
      preferredActivities: prev.preferredActivities.includes(activity)
        ? prev.preferredActivities.filter(a => a !== activity)
        : [...prev.preferredActivities, activity]
    }));
  };

  const handleSpecialNeedToggle = (need: string) => {
    setPreferences(prev => ({
      ...prev,
      specialNeeds: prev.specialNeeds.includes(need)
        ? prev.specialNeeds.filter(n => n !== need)
        : [...prev.specialNeeds, need]
    }));
  };

  const handleSave = () => {
    onSave(preferences);
    setIsVisible(false);
  };

  const activities = [
    { value: 'sightseeing', label: '观光游览', icon: Camera },
    { value: 'food', label: '美食体验', icon: Utensils },
    { value: 'shopping', label: '购物', icon: DollarSign },
    { value: 'hiking', label: '徒步旅行', icon: Sun },
    { value: 'culture', label: '文化体验', icon: MapPin },
    { value: 'transport', label: '交通体验', icon: Car },
    { value: 'accommodation', label: '特色住宿', icon: Hotel }
  ];

  const specialNeeds = [
    '儿童友好',
    '老人友好',
    '无障碍设施',
    '宠物友好',
    '素食选项',
    '宗教需求'
  ];

  return (
    <div className="relative">
      {/* 偏好设置按钮 */}
      <button
        onClick={() => setIsVisible(!isVisible)}
        className="flex items-center gap-2 px-4 py-2 rounded-full border border-border bg-background text-sm font-medium text-foreground hover:bg-muted transition-colors"
      >
        <Settings className="h-4 w-4" />
        偏好设置
      </button>

      {/* 偏好设置面板 */}
      {isVisible && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 max-w-[95vw] rounded-2xl border border-border bg-white dark:bg-slate-950 shadow-xl z-20">
          <div className="p-4 border-b border-border/70">
            <div className="flex items-center gap-2">
              <User className="h-5 w-5 text-sky-600 dark:text-sky-400" />
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">个性化偏好</h3>
            </div>
          </div>
          
          <div className="p-4 space-y-4">
            {/* 旅行风格 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">旅行风格</label>
              <select
                value={preferences.travelStyle}
                onChange={(e) => handlePreferenceChange('travelStyle', e.target.value)}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="relaxed">轻松休闲</option>
                <option value="adventurous">冒险探索</option>
                <option value="cultural">文化体验</option>
                <option value="foodie">美食之旅</option>
                <option value="family">家庭友好</option>
              </select>
            </div>

            {/* 游客类型 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">游客类型</label>
              <select
                value={preferences.travelerType}
                onChange={(e) => handlePreferenceChange('travelerType', e.target.value)}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="general">普通游客</option>
                <option value="backpacker">背包客</option>
                <option value="family">家庭旅行</option>
                <option value="luxury">奢华体验</option>
                <option value="couple">情侣旅行</option>
                <option value="elderly">老年旅行</option>
              </select>
            </div>

            {/* 预算水平 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">预算水平</label>
              <select
                value={preferences.budgetLevel}
                onChange={(e) => handlePreferenceChange('budgetLevel', e.target.value)}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="budget">经济实惠</option>
                <option value="mid">中等预算</option>
                <option value="luxury">豪华体验</option>
              </select>
            </div>

            {/* 出行季节 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">偏好季节</label>
              <select
                value={preferences.travelSeason}
                onChange={(e) => handlePreferenceChange('travelSeason', e.target.value)}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="spring">春季</option>
                <option value="summer">夏季</option>
                <option value="autumn">秋季</option>
                <option value="winter">冬季</option>
              </select>
            </div>

            {/* 出行人数 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">出行人数</label>
              <input
                type="number"
                min="1"
                max="20"
                value={preferences.groupSize}
                onChange={(e) => handlePreferenceChange('groupSize', parseInt(e.target.value))}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm"
              />
            </div>

            {/* 偏好活动 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">偏好活动</label>
              <div className="flex flex-wrap gap-2">
                {activities.map((activity) => {
                  const Icon = activity.icon;
                  return (
                    <button
                      key={activity.value}
                      onClick={() => handleActivityToggle(activity.value)}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                        preferences.preferredActivities.includes(activity.value)
                          ? 'bg-sky-500 text-white shadow-sm'
                          : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
                      }`}
                    >
                      <Icon className="h-3 w-3" />
                      {activity.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 特殊需求 */}
            <div>
              <label className="block text-sm font-medium text-slate-900 dark:text-slate-50 mb-2">特殊需求</label>
              <div className="flex flex-wrap gap-2">
                {specialNeeds.map((need) => (
                  <button
                    key={need}
                    onClick={() => handleSpecialNeedToggle(need)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                      preferences.specialNeeds.includes(need)
                        ? 'bg-purple-500 text-white shadow-sm'
                        : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
                    }`}
                  >
                    {need}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 保存按钮 */}
          <div className="p-4 border-t border-border/70">
            <button
              onClick={handleSave}
              className="w-full flex items-center justify-center gap-2 rounded-xl border border-sky-500 bg-sky-500 text-white px-4 py-2 text-sm font-medium transition-all hover:bg-sky-600 hover:shadow-md"
            >
              <Save className="h-4 w-4" />
              保存偏好
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export { PreferenceSettings };
export type { UserPreferences };