"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Loader2, Lock, Mail, User, Zap, Check, X } from "lucide-react"
import Link from "next/link"
import { API_BASE_URL } from "@/config"

export default function SignupPage() {
    const router = useRouter()
    const [email, setEmail] = useState("")
    const [password, setPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [fullName, setFullName] = useState("")
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(false)

    // Password strength checks
    const hasMinLength = password.length >= 8
    const hasUpperCase = /[A-Z]/.test(password)
    const hasLowerCase = /[a-z]/.test(password)
    const hasNumber = /[0-9]/.test(password)
    const passwordsMatch = password === confirmPassword && password.length > 0

    const isPasswordValid = hasMinLength && hasUpperCase && hasLowerCase && hasNumber

    const handleSignup = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")

        if (!isPasswordValid) {
            setError("Please meet all password requirements")
            return
        }

        if (!passwordsMatch) {
            setError("Passwords do not match")
            return
        }

        setLoading(true)

        try {
            const response = await fetch(`${API_BASE_URL}/auth/register`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    email,
                    password,
                    full_name: fullName,
                }),
            })

            const data = await response.json()

            if (!response.ok) {
                throw new Error(data.detail || "Registration failed")
            }

            // Redirect to login page
            router.push("/login?registered=true")
        } catch (err: any) {
            setError(err.message || "An error occurred during registration")
        } finally {
            setLoading(false)
        }
    }

    const RequirementItem = ({ met, text }: { met: boolean; text: string }) => (
        <div className={`flex items-center gap-2 text-sm transition-colors ${met ? "text-green-400" : "text-gray-400"}`}>
            {met ? <Check className="w-4 h-4" /> : <X className="w-4 h-4" />}
            <span>{text}</span>
        </div>
    )

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 flex items-center justify-center p-6">
            {/* Animated background elements */}
            <div className="absolute inset-0 overflow-hidden">
                <div className="absolute -top-40 -right-40 w-80 h-80 bg-purple-500 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob"></div>
                <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-blue-500 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob animation-delay-2000"></div>
                <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-pink-500 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-blob animation-delay-4000"></div>
            </div>

            <Card className="w-full max-w-md relative backdrop-blur-xl bg-white/10 border-white/20 shadow-2xl">
                <div className="p-8">
                    {/* Logo and Title */}
                    <div className="flex flex-col items-center mb-8">
                        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center mb-4 shadow-lg">
                            <Zap className="w-8 h-8 text-white" />
                        </div>
                        <h1 className="text-3xl font-bold text-white mb-2">Create Account</h1>
                        <p className="text-gray-300 text-center">Join us to get started</p>
                    </div>

                    {/* Error Alert */}
                    {error && (
                        <Alert className="mb-6 bg-red-500/10 border-red-500/50 text-red-200">
                            <AlertDescription>{error}</AlertDescription>
                        </Alert>
                    )}

                    {/* Signup Form */}
                    <form onSubmit={handleSignup} className="space-y-5">
                        <div className="space-y-2">
                            <Label htmlFor="fullName" className="text-gray-200">Full Name</Label>
                            <div className="relative">
                                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                                <Input
                                    id="fullName"
                                    type="text"
                                    placeholder="John Doe"
                                    value={fullName}
                                    onChange={(e) => setFullName(e.target.value)}
                                    required
                                    className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-gray-400 focus:border-purple-500 focus:ring-purple-500"
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="email" className="text-gray-200">Email</Label>
                            <div className="relative">
                                <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                                <Input
                                    id="email"
                                    type="email"
                                    placeholder="you@example.com"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-gray-400 focus:border-purple-500 focus:ring-purple-500"
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="password" className="text-gray-200">Password</Label>
                            <div className="relative">
                                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                                <Input
                                    id="password"
                                    type="password"
                                    placeholder="••••••••"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-gray-400 focus:border-purple-500 focus:ring-purple-500"
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="confirmPassword" className="text-gray-200">Confirm Password</Label>
                            <div className="relative">
                                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                                <Input
                                    id="confirmPassword"
                                    type="password"
                                    placeholder="••••••••"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    required
                                    className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-gray-400 focus:border-purple-500 focus:ring-purple-500"
                                />
                            </div>
                        </div>

                        {/* Password Requirements */}
                        {password && (
                            <div className="bg-white/5 border border-white/10 rounded-lg p-4 space-y-2">
                                <p className="text-sm font-medium text-gray-200 mb-2">Password Requirements:</p>
                                <RequirementItem met={hasMinLength} text="At least 8 characters" />
                                <RequirementItem met={hasUpperCase} text="One uppercase letter" />
                                <RequirementItem met={hasLowerCase} text="One lowercase letter" />
                                <RequirementItem met={hasNumber} text="One number" />
                                {confirmPassword && (
                                    <RequirementItem met={passwordsMatch} text="Passwords match" />
                                )}
                            </div>
                        )}

                        <Button
                            type="submit"
                            disabled={loading || !isPasswordValid || !passwordsMatch}
                            className="w-full bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white font-semibold py-6 rounded-lg shadow-lg hover:shadow-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                                    Creating account...
                                </>
                            ) : (
                                "Create Account"
                            )}
                        </Button>
                    </form>

                    {/* Divider */}
                    <div className="relative my-6">
                        <div className="absolute inset-0 flex items-center">
                            <div className="w-full border-t border-white/10"></div>
                        </div>
                        <div className="relative flex justify-center text-sm">
                            <span className="px-2 bg-transparent text-gray-400">Already have an account?</span>
                        </div>
                    </div>

                    {/* Login Link */}
                    <Link href="/login">
                        <Button
                            variant="outline"
                            className="w-full border-white/20 text-white hover:bg-white/10 hover:border-white/30"
                        >
                            Sign In
                        </Button>
                    </Link>
                </div>
            </Card>
        </div>
    )
}
