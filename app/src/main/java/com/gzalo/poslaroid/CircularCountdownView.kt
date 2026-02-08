package com.gzalo.poslaroid

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.min

class CircularCountdownView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.DKGRAY
        style = Paint.Style.STROKE
        strokeWidth = 12f
    }

    private val progressPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 12f
        strokeCap = Paint.Cap.ROUND
    }

    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        textSize = 64f
        isFakeBoldText = true
    }

    private val arcRect = RectF()
    private var sweepAngle = 360f
    private var remainingSeconds = 4
    private var animator: ValueAnimator? = null
    private var onFinished: (() -> Unit)? = null

    fun start(durationMs: Long, onFinished: () -> Unit) {
        this.onFinished = onFinished
        remainingSeconds = (durationMs / 1000).toInt()

        animator?.cancel()
        animator = ValueAnimator.ofFloat(360f, 0f).apply {
            duration = durationMs
            interpolator = LinearInterpolator()
            addUpdateListener { animation ->
                sweepAngle = animation.animatedValue as Float
                val fraction = 1f - animation.animatedFraction
                remainingSeconds = kotlin.math.ceil((fraction * durationMs / 1000).toDouble()).toInt()
                invalidate()
            }
            addListener(object : android.animation.AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: android.animation.Animator) {
                    this@CircularCountdownView.onFinished?.invoke()
                }
            })
            start()
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val cx = width / 2f
        val cy = height / 2f
        val radius = min(cx, cy) - backgroundPaint.strokeWidth

        arcRect.set(cx - radius, cy - radius, cx + radius, cy + radius)

        // Background circle
        canvas.drawCircle(cx, cy, radius, backgroundPaint)

        // Countdown arc (starts from top, -90 degrees)
        if (sweepAngle > 0f) {
            canvas.drawArc(arcRect, -90f, sweepAngle, false, progressPaint)
        }

        // Seconds text
        val textY = cy - (textPaint.descent() + textPaint.ascent()) / 2
        canvas.drawText("$remainingSeconds", cx, textY, textPaint)
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        animator?.cancel()
    }
}
